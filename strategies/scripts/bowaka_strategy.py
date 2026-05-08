#!/usr/bin/env python3
"""
bowaka_strategy.py — OpenAlgo /python strategy that consumes the Bowaka
prefilter and trades through Alpaca via OpenAlgo's promoted v2 API.

Companion artifact: ``strategies/scripts/bowaka_prefilter.py`` (already
built, scheduled, running). This file is the trading-side counterpart.

Phase 1 — skeleton: CLI bootstrap, config loader, logging, state
management, session window check, kill switch detection, signal
handlers, no-op main loop. Order placement, candidate ingestion, and
exits arrive in later phases.

State is modelled as a plain ``TypedDict``; the schema is documented
inline below so the runbook can point at one canonical place.

Auth: ``OPENALGO_API_KEY`` from env. Host: ``HOST_SERVER`` (default
http://127.0.0.1:5000). The ``/python`` host launches with
``OPENALGO_STRATEGY_EXCHANGE=CRYPTO`` so the host's Indian holiday gate
does not fire — the strategy enforces its own NYSE session window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as _dtime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

import httpx
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yaml

LOG = logging.getLogger("bowaka_strategy")

# ---------------------------------------------------------------- state schema

# State JSON shape (version 1):
#
#   {
#     "version": 1,
#     "strategy_id": "bowaka",
#     "session_date": null | "YYYY-MM-DD",
#     "daily_pnl_baseline_equity": null | float,
#     "daily_pnl_tripped": false,
#     "open_positions": {
#       "<ticker>": {
#         "parent_order_id": str,
#         "child_order_ids": {"target": str, "stop": str},
#         "qty": int,
#         "entry_price": float | null,
#         "entry_timestamp": iso8601,
#         "entry_features": {...},
#         "status": "pending_fill" | "filled" | "exiting"
#       }
#     },
#     "pending_signal_fade_exits": {
#       "<ticker>": {"submitted_at": iso8601, "exit_order_id": str}
#     },
#     "halt_skip_today": ["<ticker>", ...],
#     "kill_switch_state": null | "L1" | "L2" | "L3"
#   }


class State(TypedDict, total=False):
    version: int
    strategy_id: str
    session_date: str | None
    daily_pnl_baseline_equity: float | None
    daily_pnl_tripped: bool
    open_positions: dict[str, dict[str, Any]]
    pending_signal_fade_exits: dict[str, dict[str, Any]]
    halt_skip_today: list[str]
    kill_switch_state: str | None


def blank_state() -> State:
    return {
        "version": 1,
        "strategy_id": "bowaka",
        "session_date": None,
        "daily_pnl_baseline_equity": None,
        "daily_pnl_tripped": False,
        "open_positions": {},
        "pending_signal_fade_exits": {},
        "halt_skip_today": [],
        "kill_switch_state": None,
    }


# ---------------------------------------------------------------- kill switch


class KillLevel(Enum):
    NONE = "NONE"
    L1_NEW = "L1_NEW"
    L2_SOFT = "L2_SOFT"
    L3_HARD = "L3_HARD"


KILL_FLAG_NEW = "KILL_NEW.flag"
KILL_FLAG_SOFT = "KILL_SOFT.flag"
KILL_FLAG_HARD = "KILL_HARD.flag"


def check_kill_switches(switch_dir: Path) -> KillLevel:
    """Highest-precedence flag wins: L3 > L2 > L1."""
    if (switch_dir / KILL_FLAG_HARD).exists():
        return KillLevel.L3_HARD
    if (switch_dir / KILL_FLAG_SOFT).exists():
        return KillLevel.L2_SOFT
    if (switch_dir / KILL_FLAG_NEW).exists():
        return KillLevel.L1_NEW
    return KillLevel.NONE


# ---------------------------------------------------------------- config


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def config_hash(cfg: dict) -> str:
    """Stable short hash so the strategy can detect a config drift —
    matches the prefilter's hashing scheme byte-for-byte (sha256, first
    8 hex chars, sort_keys, default=str)."""
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:8]


def setup_logging(cfg: dict) -> None:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper())
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if path := log_cfg.get("file"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


# Item 8 — gate-drift handshake. The reviewer's exact ask:
#
#   "either pin the expected prefilter hash or load the prefilter
#    config at strategy startup and compare the signal gates and
#    indicators."
#
# Auto-pinning is brittle (drifts silently); we go with the second
# option. At startup we open the prefilter yaml and assert that every
# signal_gates / indicators key has the same value on both sides.
# Any mismatch raises HandshakeMismatch so the operator notices on
# the very first tick.
class HandshakeMismatch(RuntimeError):
    """Raised when the strategy yaml's signal_gates / indicators
    don't match the prefilter yaml's. Means the EOD signal-fade
    re-evaluation would use thresholds the prefilter never applied
    when picking candidates."""


def verify_prefilter_handshake(
    cfg: dict,
    *,
    prefilter_yaml_path: str | Path | None = None,
) -> None:
    """Cross-check that the strategy and prefilter agree on signal
    thresholds and indicator windows. Item 8 (handshake): even with
    ``prefilter_handshake.expected_config_hash=null`` the operator
    gets a loud failure when the two yamls drift.

    The path is resolved as:
      1. ``cfg.prefilter_handshake.prefilter_yaml_path`` if set
      2. ``prefilter_yaml_path`` keyword (test override)
      3. a sibling file at ``strategies/scripts/bowaka_prefilter.yaml``
    Missing prefilter yaml → log a warning and return (don't fail
    just because someone moved files around).
    """
    handshake_cfg = cfg.get("prefilter_handshake") or {}
    path = (
        handshake_cfg.get("prefilter_yaml_path")
        or prefilter_yaml_path
        or (Path(__file__).resolve().parent / "bowaka_prefilter.yaml")
    )
    p = Path(path)
    if not p.exists():
        LOG.warning(
            "verify_prefilter_handshake: %s not found — skipping gate cross-check. "
            "Set cfg.prefilter_handshake.prefilter_yaml_path to enable.", p,
        )
        return

    with open(p) as f:
        prefilter_cfg = yaml.safe_load(f) or {}

    pf_signals = (prefilter_cfg.get("signals") or {})
    st_gates = (cfg.get("signal_gates") or {})
    pf_inds = (prefilter_cfg.get("indicators") or {})
    st_inds = (cfg.get("indicators") or {})

    drift: list[str] = []
    # Compare every key the strategy declares to the matching prefilter
    # value. Missing prefilter keys are also drift — the prefilter
    # wasn't gating on something the signal_fade exit re-checks.
    for k, st_v in st_gates.items():
        pf_v = pf_signals.get(k)
        if pf_v != st_v:
            drift.append(
                f"signal_gates.{k}: strategy={st_v!r} prefilter={pf_v!r}"
            )
    for k, st_v in st_inds.items():
        pf_v = pf_inds.get(k)
        if pf_v != st_v:
            drift.append(
                f"indicators.{k}: strategy={st_v!r} prefilter={pf_v!r}"
            )

    if drift:
        raise HandshakeMismatch(
            "strategy and prefilter configs disagree — signal-fade "
            "exits would use different thresholds than the entry "
            "prefilter:\n  " + "\n  ".join(drift)
            + "\nFix the drift in either yaml and restart."
        )
    LOG.info(
        "prefilter handshake verified: %d gates + %d indicator settings match",
        len(st_gates), len(st_inds),
    )


# ---------------------------------------------------------------- state I/O


def load_state(path: Path) -> State:
    if not path.exists():
        return blank_state()
    with open(path) as f:
        raw = json.load(f)
    # Fill defaults so old state files survive new field additions.
    base = blank_state()
    base.update(raw)
    return base  # type: ignore[return-value]


def save_state(state: State, path: Path) -> None:
    """Atomic write: ``.tmp`` → fsync → rename. Safe against crash mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def reset_for_new_session(
    state: State, today_iso: str, equity: float | None
) -> None:
    """Zero daily fields without touching open_positions or pending exits."""
    state["session_date"] = today_iso
    state["daily_pnl_baseline_equity"] = equity
    state["daily_pnl_tripped"] = False
    state["halt_skip_today"] = []
    # Phase 3: dedupe flags are per-day.
    state.pop("signal_fade_evaluated_for_date", None)
    state.pop("summary_written_for_date", None)
    state.pop("daily_marks_written_for_date", None)


# ---------------------------------------------------------------- session


_NYSE = mcal.get_calendar("NYSE")


def _to_eastern(now_utc: datetime) -> datetime:
    """Convert any tz-aware (or naive-treated-as-UTC) datetime to NY tz."""
    import pytz

    et = pytz.timezone("America/New_York")
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(et)


def is_in_session(
    now_utc: datetime,
    *,
    start: str = "09:30",
    end: str = "15:55",
) -> bool:
    """09:30–15:55 ET regular session, NYSE trading day. False on
    weekends, NYSE holidays, and outside the regular window."""
    et = _to_eastern(now_utc)
    sched = _NYSE.schedule(start_date=et.date(), end_date=et.date())
    if sched.empty:
        return False
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    et_minutes = et.hour * 60 + et.minute
    return (sh * 60 + sm) <= et_minutes <= (eh * 60 + em)


def is_signal_fade_window(now_utc: datetime, eval_time: str = "16:05") -> bool:
    """True at the configured EOD evaluation minute on a NYSE trading
    day. The minute granularity is intentional — the main loop only
    needs to fire signal-fade once per day; a state flag dedupes."""
    et = _to_eastern(now_utc)
    sched = _NYSE.schedule(start_date=et.date(), end_date=et.date())
    if sched.empty:
        return False
    eh, em = (int(x) for x in eval_time.split(":"))
    return et.hour == eh and et.minute == em


# ---------------------------------------------------------------- shutdown

_shutdown_requested = False


def _request_shutdown(signum, frame):  # noqa: ARG001 — signal signature
    global _shutdown_requested
    LOG.info("Signal %s received, requesting shutdown", signum)
    _shutdown_requested = True


def shutdown_requested() -> bool:
    return _shutdown_requested


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)


# ---------------------------------------------------------------- candidates


class CandidatesError(Exception):
    """Base class for candidate-load failures."""


class CandidatesMissing(CandidatesError):
    pass


class CandidatesStaleError(CandidatesError):
    pass


class CandidatesHashMismatch(CandidatesError):
    pass


@dataclass
class Candidate:
    ticker: str
    close: float
    signal_strength: float
    # ISO 10383 MIC for /api/v2 instrument resolution. None when the
    # candidate file predates the venue-routing format (pre-Item-2);
    # callers fall back to ``cfg.sizing.default_venue_code`` in that
    # case so legacy candidate files keep working.
    venue_code: str | None = None
    exchange: str | None = None
    features: dict[str, Any] = field(default_factory=dict)


def _trading_days_between(d1_iso: str, d2_iso: str) -> int:
    """Count NYSE trading days strictly between two ISO dates inclusive
    of the start, exclusive of the end (i.e., how many trading days
    have passed)."""
    d1 = datetime.fromisoformat(d1_iso).date()
    d2 = datetime.fromisoformat(d2_iso).date() if isinstance(d2_iso, str) else d2_iso
    if d1 > d2:
        return 0
    sched = _NYSE.schedule(start_date=d1, end_date=d2)
    # Trading days behind: (today's index) - (as_of's index).
    if sched.empty:
        return 0
    # Number of trading days BETWEEN d1 and d2 (excluding d1 itself).
    return max(0, len(sched) - 1)


def load_candidates(
    path: Path | str,
    *,
    max_age_trading_days: int,
    expected_config_hash: str | None,
    today_et: date,
) -> list[Candidate]:
    """Load + validate the prefilter's candidates JSON.

    Validates ``as_of_date`` is at most ``max_age_trading_days`` *trading*
    days behind ``today_et`` (NYSE calendar). Validates ``config_hash``
    matches ``expected_config_hash`` when pinned. Returns the
    candidates list sorted by ``signal_strength`` descending.
    """
    p = Path(path)
    if not p.exists():
        raise CandidatesMissing(f"candidates file not found: {p}")
    with open(p) as f:
        payload = json.load(f)

    if expected_config_hash is not None:
        seen = payload.get("config_hash")
        if seen != expected_config_hash:
            raise CandidatesHashMismatch(
                f"config_hash mismatch: got {seen!r}, expected {expected_config_hash!r}"
            )

    as_of_iso = payload.get("as_of_date")
    if as_of_iso is None:
        raise CandidatesStaleError("candidates missing as_of_date")
    age = _trading_days_between(as_of_iso, today_et.isoformat())
    if age > max_age_trading_days:
        raise CandidatesStaleError(
            f"candidates {age} trading days behind today (max={max_age_trading_days})"
        )

    out: list[Candidate] = []
    for row in payload.get("candidates", []):
        out.append(Candidate(
            ticker=row["ticker"],
            close=float(row["close"]),
            signal_strength=float(row.get("signal_strength") or 0.0),
            venue_code=row.get("venue_code") or None,
            exchange=row.get("exchange") or None,
            features={k: row.get(k) for k in (
                "rvol", "atr_pct", "range_expansion", "gap_pct",
                "close_location", "ema_distance", "ema_slope",
                "avg_dollar_volume",
            )},
        ))
    out.sort(key=lambda c: c.signal_strength, reverse=True)
    return out


# ---------------------------------------------------------------- http client


def make_http_client(
    base_url: str,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Plain httpx.Client. Tests pass an httpx.MockTransport."""
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "timeout": timeout,
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


def _api_headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------- equity


def fetch_equity(http: httpx.Client, api_key: str) -> float:
    """GET /api/v2/balances and return the equity figure.

    Returns ``equity`` when the broker adapter populates it; falls back
    to ``cash`` so India brokers (which have no equity field in the
    balance response) still produce a usable number for sizing.
    """
    r = http.get("/api/v2/balances",
                 headers=_api_headers(api_key),
                 params={"apikey": api_key})
    r.raise_for_status()
    body = r.json().get("data") or {}
    bal = body.get("balance") or body.get("balances") or {}
    if isinstance(bal, dict):
        if "equity" in bal and bal["equity"] is not None:
            return float(bal["equity"])
        if "cash" in bal and bal["cash"] is not None:
            return float(bal["cash"])
    raise RuntimeError(f"could not parse equity from /api/v2/balances response: {body!r}")


# ---------------------------------------------------------------- sizing


def compute_qty(
    equity: float,
    close_price: float,
    per_trade_pct: float,
    max_per_trade_dollars: float | None = None,
    *,
    avg_dollar_volume: float | None = None,
    max_position_as_adv_frac: float | None = None,
) -> int:
    """floor(min(equity*pct, abs_cap, adv_cap) / close). Whole shares
    only — bracket orders reject fractional at Alpaca. Returns 0 when
    the target dollars don't cover one share (caller skips).

    The ADV cap (Item 3 / expert review) is the strategy's stated
    capacity edge. Without it a $1M account at 10% per-trade puts $100k
    into a name with $250k ADV — a 40% participation rate that
    contradicts the capacity-limited thesis. Pass both
    ``avg_dollar_volume`` (from the candidate features) and
    ``max_position_as_adv_frac`` (from ``cfg.risk``) to enable the cap.
    """
    target = equity * per_trade_pct
    if max_per_trade_dollars is not None:
        target = min(target, max_per_trade_dollars)
    if (
        avg_dollar_volume is not None
        and max_position_as_adv_frac is not None
        and avg_dollar_volume > 0
        and max_position_as_adv_frac > 0
    ):
        target = min(target, avg_dollar_volume * max_position_as_adv_frac)
    if close_price <= 0 or target <= 0:
        return 0
    return int(math.floor(target / close_price))


def current_gross_exposure(
    open_positions: dict[str, dict[str, Any]],
    latest_prices: dict[str, float],
) -> float:
    total = 0.0
    for ticker, pos in open_positions.items():
        qty = float(pos.get("qty") or 0)
        price = latest_prices.get(ticker)
        if price is None:
            price = pos.get("entry_price")
        if price is None:
            continue
        total += qty * float(price)
    return total


# ---------------------------------------------------------------- entry


@dataclass
class Entry:
    ticker: str
    qty: int
    close_price: float
    venue_code: str
    candidate: Candidate
    # Captured for the ``opened`` jsonl record so the analyst can see
    # the sizing rationale at the moment of submission. None when the
    # entry was constructed by older callers / tests that didn't supply
    # it; the opened-record writer falls back gracefully.
    equity_at_entry: float | None = None


def select_entries(
    candidates: list[Candidate],
    state: State,
    *,
    equity: float,
    latest_prices: dict[str, float],
    cfg: dict,
    kill_state: KillLevel,
) -> list[Entry]:
    """Walk candidates in signal_strength order, applying the entry
    gates from the architecture decisions. Returns the slate of
    accepted entries (bounded by max_concurrent_positions and gross
    exposure)."""
    if state.get("daily_pnl_tripped"):
        return []
    if kill_state in (KillLevel.L1_NEW, KillLevel.L2_SOFT, KillLevel.L3_HARD):
        return []

    sizing_cfg = cfg["sizing"]
    risk_cfg = cfg["risk"]
    max_concurrent = int(sizing_cfg["max_concurrent_positions"])
    per_trade_pct = float(sizing_cfg["per_trade_pct"])
    max_per_trade_abs = risk_cfg.get("max_per_trade_dollars")
    # Item 3: capacity / ADV-participation cap. Disabled when null.
    max_pos_adv = risk_cfg.get("max_position_as_adv_frac")
    max_pos_adv_f = float(max_pos_adv) if max_pos_adv is not None else None

    pct_cap = float(risk_cfg.get("max_gross_exposure_pct") or 0.0) * equity
    abs_cap = risk_cfg.get("max_gross_exposure_dollars")
    gross_cap = abs_cap if abs_cap is not None else pct_cap

    open_positions = state.get("open_positions") or {}
    halt_skip = set(state.get("halt_skip_today") or [])

    selected: list[Entry] = []
    running_gross = current_gross_exposure(open_positions, latest_prices)
    open_count = len(open_positions)

    for cand in candidates:
        if cand.ticker in halt_skip:
            continue
        if cand.ticker in open_positions:
            continue
        if open_count + len(selected) >= max_concurrent:
            break
        adv = cand.features.get("avg_dollar_volume") if cand.features else None
        adv_f = float(adv) if adv is not None else None
        qty = compute_qty(
            equity=equity,
            close_price=cand.close,
            per_trade_pct=per_trade_pct,
            max_per_trade_dollars=max_per_trade_abs,
            avg_dollar_volume=adv_f,
            max_position_as_adv_frac=max_pos_adv_f,
        )
        if qty <= 0:
            continue
        notional = qty * cand.close
        if gross_cap > 0 and (running_gross + notional) > gross_cap:
            continue
        running_gross += notional
        # Per-candidate venue routing. Falls back to the strategy's
        # default_venue_code when the candidate file predates the
        # venue-routing format (pre-Item-2 universe cache).
        venue_code = cand.venue_code or sizing_cfg["default_venue_code"]
        selected.append(Entry(
            ticker=cand.ticker,
            qty=qty,
            close_price=cand.close,
            venue_code=venue_code,
            candidate=cand,
            equity_at_entry=equity,
        ))
    return selected


# ---------------------------------------------------------------- OTOCO


# Bracket-pricing modes. Configured via ``cfg.entry.bracket_pricing_mode``.
#
# * ``"actual_fill"`` (default) — Item 4 fix. Submit the parent MARKET
#   BUY alone, wait for the fill, then submit the OCO take_profit /
#   stop_loss bracket using ``filled_avg_price`` as the reference. This
#   removes the gap-risk regression where a microcap that opens 30%
#   above yesterday's close could ship with a take-profit BELOW the
#   actual fill price (broker-side rejection or instant-target risk).
# * ``"candidate_close"`` — legacy single-shot OTOCO with target / stop
#   priced off the prefilter's prior close. Preserved for backtest
#   parity / debugging.
BRACKET_PRICING_MODES = {"actual_fill", "candidate_close"}


def _bracket_pricing_mode(cfg: dict) -> str:
    mode = (cfg.get("entry") or {}).get("bracket_pricing_mode") or "actual_fill"
    if mode not in BRACKET_PRICING_MODES:
        raise ValueError(
            f"cfg.entry.bracket_pricing_mode must be one of "
            f"{sorted(BRACKET_PRICING_MODES)}; got {mode!r}"
        )
    return mode


# ---------------------------------------------------------------- Item 9 intraday confirmation


def _intraday_confirmation_cfg(cfg: dict) -> dict:
    return ((cfg.get("entry") or {}).get("intraday_confirmation") or {})


def _intraday_window_elapsed(cfg: dict, now_utc: datetime, today_et: date) -> bool:
    """Return True if at least ``window_minutes`` have elapsed since
    today's session start. ``window_minutes <= 0`` always returns True
    (gate disabled)."""
    import pytz  # already a strategy dependency; keep lazy to match the rest of the file

    ic = _intraday_confirmation_cfg(cfg)
    window_min = float(ic.get("window_minutes") or 0)
    if window_min <= 0:
        return True
    session = cfg.get("session") or {}
    start_str = session.get("start") or "09:30"
    tz_name = session.get("timezone") or "America/New_York"
    try:
        h, m = (int(p) for p in start_str.split(":")[:2])
    except Exception:
        h, m = 9, 30
    tz = pytz.timezone(tz_name)
    session_start = tz.localize(datetime.combine(today_et, _dtime(h, m)))
    now_local = now_utc.astimezone(tz)
    return (now_local - session_start) >= timedelta(minutes=window_min)


def _fetch_quote(
    entry: Entry,
    http: httpx.Client,
    api_key: str,
) -> dict[str, Any] | None:
    """POST /api/v2/quotes for a single instrument. Returns the quote
    dict on success or None on any failure — callers treat None as
    "can't confirm, skip the entry"."""
    body = {
        "apikey": api_key,
        "instruments": [{
            "venue_code": entry.venue_code,
            "canonical_symbol": entry.ticker,
        }],
    }
    try:
        r = http.post("/api/v2/quotes", json=body, headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.warning("intraday quote fetch failed for %s: %s", entry.ticker, e)
        return None
    if r.status_code != 200:
        LOG.warning(
            "intraday quote fetch returned %d for %s: %s",
            r.status_code, entry.ticker, (r.text or "")[:200],
        )
        return None
    try:
        rows = r.json().get("data") or []
    except ValueError:
        return None
    if not rows:
        return None
    return (rows[0] or {}).get("quote") or {}


def _confirm_entry(
    entry: Entry,
    cfg_ic: dict,
    quote: dict[str, Any],
    *,
    now_utc: datetime,
) -> tuple[bool, str | None]:
    """Apply the intraday gates against ``quote``. Returns
    ``(passed, fail_reason)``. fail_reason is None on pass and a
    short label on fail (used in logs and tests)."""
    try:
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
    except (TypeError, ValueError):
        return False, "bad_bid_ask"
    if bid <= 0 or ask <= 0 or ask <= bid:
        return False, "no_quote"
    mid = (bid + ask) / 2.0

    max_spread = float(cfg_ic.get("max_spread_pct") or 0)
    if max_spread > 0 and (ask - bid) / mid > max_spread:
        return False, f"spread>{max_spread:.4f}"

    max_age_s = float(cfg_ic.get("max_quote_age_seconds") or 0)
    if max_age_s > 0:
        ts = quote.get("timestamp")
        if isinstance(ts, str):
            try:
                quote_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if quote_dt.tzinfo is None:
                    quote_dt = quote_dt.replace(tzinfo=timezone.utc)
                age_s = (now_utc - quote_dt).total_seconds()
                if age_s > max_age_s:
                    return False, f"quote_age>{max_age_s:.0f}s"
            except ValueError:
                # Unparseable timestamp — be conservative and skip.
                return False, "bad_quote_timestamp"

    band = cfg_ic.get("price_band") or {}
    max_above = band.get("max_pct_above_close")
    min_below = band.get("min_pct_below_close")
    if max_above is not None and entry.close_price > 0:
        if mid > entry.close_price * (1.0 + float(max_above)):
            return False, f"chase>{max_above}"
    if min_below is not None and entry.close_price > 0:
        if mid < entry.close_price * (1.0 + float(min_below)):
            return False, f"failure<{min_below}"

    return True, None


def filter_by_intraday_confirmation(
    entries: list[Entry],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    now_utc: datetime | None = None,
) -> list[Entry]:
    """Item 9: gate each entry on a fresh quote. Skips a name when
    spread is too wide, the quote is stale, or the live price is
    outside the configured band relative to candidate.close. Returns
    the filtered list. When the gate is disabled (``enabled: false``
    or empty config) returns the input unchanged."""
    ic = _intraday_confirmation_cfg(cfg)
    if not ic.get("enabled"):
        return entries
    now_utc = now_utc or datetime.now(timezone.utc)
    out: list[Entry] = []
    for entry in entries:
        quote = _fetch_quote(entry, http, api_key)
        if quote is None:
            LOG.info(
                "intraday_confirmation: %s — no quote available, skipping",
                entry.ticker,
            )
            continue
        passed, reason = _confirm_entry(entry, ic, quote, now_utc=now_utc)
        if passed:
            out.append(entry)
        else:
            LOG.info(
                "intraday_confirmation: %s rejected (%s) bid=%s ask=%s",
                entry.ticker, reason,
                quote.get("bid"), quote.get("ask"),
            )
    return out


def submit_entry(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
) -> dict[str, Any]:
    """Dispatch to the configured bracket-pricing mode. The legacy
    ``submit_otoco`` is kept as the ``candidate_close`` implementation
    (Phase 2 contract). ``actual_fill`` uses ``submit_parent_market_buy``
    and defers child submission to ``submit_pending_oco_children``
    after the parent fill arrives in poll_fills.

    ``link_id_override`` is plumbed in by ``run_session_entry_pass``
    so the entry_decision record (written before this call) shares the
    link_id with the submitted order — that's the join key for per-
    trade jsonl files.
    """
    mode = _bracket_pricing_mode(cfg)
    if mode == "actual_fill":
        return submit_parent_market_buy(
            entry, cfg, http, api_key,
            state=state, state_path=state_path,
            link_id_override=link_id_override,
        )
    return submit_otoco(
        entry, cfg, http, api_key,
        state=state, state_path=state_path,
        link_id_override=link_id_override,
    )


def submit_parent_market_buy(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
) -> dict[str, Any]:
    """Item 4 (actual_fill mode): submit a stand-alone parent MARKET
    BUY via /api/v2/orders. The OCO take_profit / stop_loss children
    are submitted later by :func:`submit_pending_oco_children` once
    the parent's filled_avg_price is known.

    Records the same state shape as :func:`submit_otoco` but with empty
    child_order_ids and ``bracket_pricing_mode="actual_fill"`` plus
    cached ``target_pct`` / ``stop_pct`` so the post-fill submitter can
    derive the bracket levels without a second cfg dependency."""
    venue_code = entry.venue_code or cfg["sizing"]["default_venue_code"]
    link_id = link_id_override or f"BOWAKA-{entry.ticker}-{int(time.time())}"

    body = {
        "apikey": api_key,
        "instrument": {
            "venue_code": venue_code,
            "canonical_symbol": entry.ticker,
        },
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": str(entry.qty),
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
        "session": "REGULAR",
    }
    r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code == 200:
        data = parsed.get("data", {})
        native = data.get("native_response") or {}
        parent_id = (
            native.get("id")
            or native.get("order_id")
            or data.get("order_id")
            or ""
        )
        state.setdefault("open_positions", {})[entry.ticker] = {
            "parent_order_id": parent_id,
            "child_order_ids": {"target": "", "stop": ""},
            "qty": entry.qty,
            "entry_price": None,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_features": entry.candidate.features,
            "status": "pending_fill",
            "link_id": link_id,
            "venue_code": venue_code,
            "exchange": entry.candidate.exchange,
            "bracket_pricing_mode": "actual_fill",
            "target_pct": float(cfg["exits"]["target_pct"]),
            "stop_pct": float(cfg["exits"]["stop_pct"]),
            "candidate_close": entry.close_price,
            "signal_strength": entry.candidate.signal_strength,
            "equity_at_entry": entry.equity_at_entry,
            # Tracks worst/best fill-relative excursion across the
            # position's life. Initialized to entry_price on parent
            # fill; updated by write_daily_marks each session end.
            "peak_since_entry": None,
            "trough_since_entry": None,
        }
        save_state(state, state_path)
        LOG.info("Parent MARKET BUY submitted (actual_fill mode): %s qty=%d parent=%s",
                 entry.ticker, entry.qty, parent_id)
        emit_parent_submitted(
            cfg, link_id=link_id, ticker=entry.ticker,
            parent_id=parent_id, qty=entry.qty, venue_code=venue_code,
            http_status=r.status_code,
        )
        return parsed

    err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
    code = (err.get("code") or "").lower()
    msg = err.get("message") or ""

    if r.status_code == 422 and (
        "instrument" in code
        or "broker_map" in msg.lower()
        or "not mapped" in msg.lower()
    ):
        LOG.error("Instrument not mapped for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 503:
        LOG.error(
            "Promoted lane unavailable (%s); operator action required: %s",
            code, err,
        )
        return {"error": err, "status": r.status_code}

    LOG.error("Parent MARKET BUY failed for %s: HTTP %d %s",
              entry.ticker, r.status_code, parsed)
    return {"error": err, "status": r.status_code}


def submit_oco_children(
    ticker: str,
    pos: dict[str, Any],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
) -> dict[str, Any] | None:
    """Submit an OCO take_profit / stop_loss bracket against an
    already-filled parent position. Used by the actual_fill bracket
    mode after :func:`poll_fills` records the parent's fill price.

    Idempotent — if ``pos["child_order_ids"]["target"]`` already has a
    value the call short-circuits with ``None``. On submission failure
    the position is left in ``status="filled"`` with empty child IDs;
    the next tick will retry.
    """
    children = pos.get("child_order_ids") or {}
    if children.get("target") and children.get("stop"):
        return None

    fill_price = pos.get("entry_price")
    qty = int(pos.get("qty") or 0)
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    target_pct = float(pos.get("target_pct") or cfg["exits"]["target_pct"])
    stop_pct = float(pos.get("stop_pct") or cfg["exits"]["stop_pct"])

    if fill_price is None or fill_price <= 0:
        LOG.warning(
            "submit_oco_children: %s has no fill_price yet; skipping",
            ticker,
        )
        return None
    if qty <= 0:
        LOG.warning(
            "submit_oco_children: %s has qty=%d; skipping",
            ticker, qty,
        )
        return None

    target_price = round(float(fill_price) * (1.0 + target_pct), 2)
    stop_price = round(float(fill_price) * (1.0 - stop_pct), 2)
    link_id = f"{pos.get('link_id') or 'BOWAKA-' + ticker}-OCO"

    body = {
        "apikey": api_key,
        "combo_type": "OCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": link_id,
        "legs": [
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": ticker,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": str(target_price),
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": ticker,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": str(stop_price),
            },
        ],
    }
    r = http.post("/api/v2/orders/combo",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code != 200:
        err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
        LOG.error(
            "OCO bracket submission failed for %s (fill=%.4f): HTTP %d %s",
            ticker, float(fill_price), r.status_code, err,
        )
        return {"error": err, "status": r.status_code}

    data = parsed.get("data") or {}
    native = data.get("native_response") or {}
    child_orders = native.get("legs") or []
    parent_response_id = native.get("id") or native.get("order_id") or ""

    # Alpaca's OCO response shape: ``id`` is the SELL LIMIT (the
    # take-profit) and ``legs[0]`` is the SELL STOP. There's no
    # separate "main" parent — the limit order plays both roles.
    # First pass: scan legs for whichever side we can identify by
    # order_type. Second pass: if target is still empty after the
    # scan, use the response's top-level id (the limit) as target.
    # Same fallback for stop, in case the legs come back empty.
    target_id = ""
    stop_id = ""
    for leg in child_orders:
        otype = (leg.get("order_type") or leg.get("type") or "").lower()
        if "limit" in otype and not target_id:
            target_id = leg.get("id") or leg.get("order_id") or ""
        elif "stop" in otype and not stop_id:
            stop_id = leg.get("id") or leg.get("order_id") or ""
    # OCO-specific: if no LIMIT leg was seen, the parent response IS
    # the take-profit. Fall back to it before resorting to leg[0].
    if not target_id and parent_response_id:
        target_id = parent_response_id
    if not stop_id and len(child_orders) >= 1:
        # Last-resort fallback (legs[0] should already have been seen
        # as 'stop' in the first pass for OCO). Only triggers when the
        # broker surfaces leg types in a way the loop above missed.
        stop_id = child_orders[0].get("id") or ""

    pos["child_order_ids"] = {"target": target_id, "stop": stop_id}
    pos["target_price"] = target_price
    pos["stop_price"] = stop_price
    # Item-(post-rebracket): clear any prior reconcile flag so the
    # next reconcile run doesn't re-flag these IDs as stale.
    pos.pop("child_status_at_recon", None)
    save_state(state, state_path)
    LOG.info(
        "OCO bracket attached: %s fill=%.4f target=%.2f(id=%s) stop=%.2f(id=%s)",
        ticker, float(fill_price), target_price, target_id, stop_price, stop_id,
    )
    emit_bracket_attached(
        cfg, pos=pos,
        target_id=target_id, stop_id=stop_id,
        target_price=target_price, stop_price=stop_price,
    )
    return parsed


def submit_pending_oco_children(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """Idempotent post-fill bracket sweep. Walks open positions whose
    bracket_pricing_mode is "actual_fill", whose status is "filled",
    and whose child_order_ids are still empty — and submits an OCO
    take_profit / stop_loss bracket priced off the recorded
    entry_price. Called once per main-loop tick after poll_fills.

    Returns the tickers that received a fresh OCO bracket this call.
    """
    out: list[str] = []
    open_positions = state.get("open_positions") or {}
    for ticker, pos in list(open_positions.items()):
        if pos.get("bracket_pricing_mode") != "actual_fill":
            continue
        if pos.get("status") != "filled":
            continue
        children = pos.get("child_order_ids") or {}
        if children.get("target") and children.get("stop"):
            continue
        try:
            res = submit_oco_children(
                ticker, pos, cfg, http, api_key,
                state=state, state_path=state_path,
            )
        except httpx.HTTPError as e:
            LOG.exception("submit_oco_children network error for %s: %s", ticker, e)
            continue
        if res and "error" not in res:
            out.append(ticker)
    return out


def submit_otoco(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    link_id_override: str | None = None,
) -> dict[str, Any]:
    """Legacy ``candidate_close`` mode: POST /api/v2/orders/combo with
    an OTOCO bracket priced off the prefilter's prior close. Records
    state on success. Marks halt_skip_today on bracket / instrument-
    mapping 422s. Surfaces 503 translator/lane errors loudly.

    Kept for backtest parity / debugging. Production runs default to
    the ``actual_fill`` mode (see :func:`submit_entry`).
    """
    target = round(entry.close_price * (1.0 + float(cfg["exits"]["target_pct"])), 2)
    stop = round(entry.close_price * (1.0 - float(cfg["exits"]["stop_pct"])), 2)
    # Item 2: route per-candidate. The prefilter's universe spans
    # NASDAQ/NYSE/AMEX/ARCA/BATS, and a hardcoded XNAS used to make
    # /api/v2 instrument resolution fail for every non-NASDAQ ticker.
    venue_code = entry.venue_code or cfg["sizing"]["default_venue_code"]
    link_id = link_id_override or f"BOWAKA-{entry.ticker}-{int(time.time())}"

    body = {
        "apikey": api_key,
        "combo_type": "OTOCO",
        "time_in_force": "DAY",
        "session": "REGULAR",
        "link_id": link_id,
        "legs": [
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "BUY",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "MARKET",
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "SELL",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": str(target),
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": entry.ticker,
                },
                "side": "SELL",
                "quantity": str(entry.qty),
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": str(stop),
            },
        ],
    }
    r = http.post("/api/v2/orders/combo",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}

    if r.status_code == 200:
        data = parsed.get("data", {})
        native = data.get("native_response") or {}
        # Alpaca's bracket native response: parent has ``id``; child
        # orders sit under ``legs`` (alpaca naming).
        parent_id = native.get("id") or native.get("order_id") or ""
        children = native.get("legs") or []
        target_id = ""
        stop_id = ""
        for leg in children:
            otype = (leg.get("order_type") or leg.get("type") or "").lower()
            if "limit" in otype and not target_id:
                target_id = leg.get("id") or leg.get("order_id") or ""
            elif "stop" in otype and not stop_id:
                stop_id = leg.get("id") or leg.get("order_id") or ""
        # Fallback for translators that surface the children differently.
        if not target_id and len(children) >= 1:
            target_id = children[0].get("id") or ""
        if not stop_id and len(children) >= 2:
            stop_id = children[1].get("id") or ""

        state.setdefault("open_positions", {})[entry.ticker] = {
            "parent_order_id": parent_id,
            "child_order_ids": {"target": target_id, "stop": stop_id},
            "qty": entry.qty,
            "entry_price": None,
            "entry_timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_features": entry.candidate.features,
            "status": "pending_fill",
            "link_id": link_id,
            "venue_code": venue_code,
            "exchange": entry.candidate.exchange,
            "target_price": target,
            "stop_price": stop,
            # Same analytic-logging fields as submit_parent_market_buy
            # so the candidate_close mode produces comparable opened
            # records.
            "bracket_pricing_mode": "candidate_close",
            "target_pct": float(cfg["exits"]["target_pct"]),
            "stop_pct": float(cfg["exits"]["stop_pct"]),
            "candidate_close": entry.close_price,
            "signal_strength": entry.candidate.signal_strength,
            "equity_at_entry": entry.equity_at_entry,
            "peak_since_entry": None,
            "trough_since_entry": None,
        }
        save_state(state, state_path)
        LOG.info("OTOCO submitted: %s qty=%d parent=%s",
                 entry.ticker, entry.qty, parent_id)
        emit_parent_submitted(
            cfg, link_id=link_id, ticker=entry.ticker,
            parent_id=parent_id, qty=entry.qty, venue_code=venue_code,
            http_status=r.status_code,
        )
        # In legacy candidate_close mode the bracket children come
        # back atomically with the parent, so we record the
        # bracket-attached event right here using the IDs already
        # parsed above.
        emit_bracket_attached(
            cfg, pos=state["open_positions"][entry.ticker],
            target_id=target_id, stop_id=stop_id,
            target_price=target, stop_price=stop,
        )
        return parsed

    err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
    code = (err.get("code") or "").lower()
    msg = err.get("message") or ""

    if r.status_code == 422 and (
        code == "unsupported_capability"
        and "bracket" in str(err.get("details", {})).lower()
    ):
        LOG.error("OTOCO bracket capability rejected for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 422 and (
        "instrument" in code
        or "instrument_not_resolvable" in code
        or "broker_map" in msg.lower()
        or "not mapped" in msg.lower()
    ):
        LOG.error("Instrument not mapped for %s: %s", entry.ticker, err)
        state.setdefault("halt_skip_today", []).append(entry.ticker)
        save_state(state, state_path)
        return {"error": err, "status": r.status_code}

    if r.status_code == 503:
        LOG.error(
            "Promoted lane unavailable (%s); operator action required: %s",
            code, err,
        )
        return {"error": err, "status": r.status_code}

    # Anything else — log and skip the ticker for safety; do NOT add to
    # halt list (might be a transient broker error worth retrying next session).
    LOG.error("OTOCO submission failed for %s (HTTP %d): %s",
              entry.ticker, r.status_code, parsed)
    return {"error": err or {"code": "unknown"}, "status": r.status_code}


# ---------------------------------------------------------------- single market


def submit_market_sell(
    ticker: str,
    qty: int,
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    time_in_force: str = "DAY",
) -> dict[str, Any]:
    """POST /api/v2/orders with a single SELL MARKET. Phase 3 passes
    ``time_in_force='OPG'`` for MOO."""
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "side": "SELL",
        "order_type": "MARKET",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "time_in_force": time_in_force,
    }
    r = http.post("/api/v2/orders",
                  json=body,
                  headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


# ---------------------------------------------------------------- cancel


def cancel_order(order_id: str, http: httpx.Client, api_key: str) -> dict[str, Any]:
    """DELETE /api/v2/orders/<id>. Idempotent on 404 / already-closed."""
    if not order_id:
        return {"status": "noop", "reason": "no order_id"}
    r = http.request(
        "DELETE", f"/api/v2/orders/{order_id}",
        headers=_api_headers(api_key),
        params={"apikey": api_key},
    )
    parsed = r.json() if r.content else {}
    if r.status_code == 200:
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    if r.status_code == 404:
        LOG.debug("cancel %s: 404 (already gone) — treating as success", order_id)
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    err_msg = ""
    if isinstance(parsed, dict):
        err = parsed.get("error") or {}
        err_msg = (err.get("message") or "").lower()
    if any(k in err_msg for k in (
        "already inactive", "already_inactive",
        "already canceled", "already_canceled",
        "not found", "not_found",
    )):
        LOG.debug("cancel %s: idempotent terminal state — treating as success", order_id)
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    raise RuntimeError(f"cancel_order failed for {order_id}: HTTP {r.status_code} {parsed}")


# ---------------------------------------------------------------- fill polling


@dataclass
class FillEvent:
    ticker: str
    order_id: str
    role: str  # "parent", "target", "stop"
    status: str
    filled_qty: int
    filled_avg_price: float | None
    raw: dict[str, Any]


def _build_order_index(state: State) -> dict[str, tuple[str, str]]:
    """Map order_id -> (ticker, role)."""
    idx: dict[str, tuple[str, str]] = {}
    for ticker, pos in (state.get("open_positions") or {}).items():
        if pid := pos.get("parent_order_id"):
            idx[pid] = (ticker, "parent")
        for role, oid in (pos.get("child_order_ids") or {}).items():
            if oid:
                idx[oid] = (ticker, role)
        if eid := pos.get("exit_order_id"):
            idx[eid] = (ticker, "exit")
    for ticker, pend in (state.get("pending_signal_fade_exits") or {}).items():
        if oid := pend.get("exit_order_id"):
            idx[oid] = (ticker, "exit")
    return idx


_FILLED = {"filled", "FILLED"}
_PENDING = {"new", "accepted", "pending_new", "pending", "partially_filled",
            "NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED"}
_DEAD = {"canceled", "cancelled", "rejected", "expired", "replaced",
         "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED",
         "done_for_day", "DONE_FOR_DAY"}


def poll_fills(
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    cfg: dict | None = None,
) -> list[FillEvent]:
    """GET /api/v2/orders?status=all and reconcile fills against state.

    Updates state in place and persists on any change. Returns the list
    of detected fill events for the caller (Phase 3 uses these to drive
    position closures).
    """
    if not state.get("open_positions") and not state.get("pending_signal_fade_exits"):
        return []

    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"apikey": api_key, "status": "all"})
    r.raise_for_status()
    body = r.json().get("data") or {}
    rows = body.get("orders") or []
    idx = _build_order_index(state)
    events: list[FillEvent] = []
    dirty = False

    open_positions = state.setdefault("open_positions", {})

    for row in rows:
        oid = row.get("id") or row.get("order_id") or ""
        if oid not in idx:
            continue
        ticker, role = idx[oid]
        # Native status comes back from the broker (e.g. Alpaca
        # "filled"); the v2 layer also exposes ``canonical_status`` for
        # translators that implement ``normalize_order_status``. Either
        # is fine for our taxonomy.
        status = row.get("native_status") or row.get("status") or ""
        canonical = (row.get("canonical_status") or status).upper()
        filled_qty = int(float(row.get("filled_qty") or row.get("filled_quantity") or 0))
        filled_avg = row.get("filled_avg_price")
        try:
            filled_avg_f = float(filled_avg) if filled_avg is not None else None
        except (ValueError, TypeError):
            filled_avg_f = None
        ev = FillEvent(
            ticker=ticker, order_id=oid, role=role,
            status=canonical, filled_qty=filled_qty,
            filled_avg_price=filled_avg_f, raw=row,
        )

        pos = open_positions.get(ticker)

        if role == "parent" and pos is not None:
            if status in _FILLED or canonical == "FILLED":
                if pos.get("status") != "filled":
                    pos["status"] = "filled"
                    pos["entry_price"] = filled_avg_f or pos.get("entry_price")
                    if filled_qty > 0:
                        pos["qty"] = filled_qty
                    # Initialize MFE/MAE excursion tracking at the
                    # actual fill price. write_daily_marks updates these
                    # at each session end with the day's high/low.
                    if pos.get("entry_price") is not None:
                        pos["peak_since_entry"] = float(pos["entry_price"])
                        pos["trough_since_entry"] = float(pos["entry_price"])
                    dirty = True
                    events.append(ev)
                    # Per-trade rich log: parent fill is a state
                    # transition we want a record for.
                    emit_entry_fill(cfg, pos=pos, ev=ev)
            elif status in _DEAD or canonical in {s.upper() for s in _DEAD}:
                if filled_qty > 0:
                    # Partial fill before cancel/reject — keep the
                    # filled portion and log the remainder.
                    pos["status"] = "filled"
                    pos["qty"] = filled_qty
                    pos["entry_price"] = filled_avg_f or pos.get("entry_price")
                    if pos.get("entry_price") is not None:
                        pos["peak_since_entry"] = float(pos["entry_price"])
                        pos["trough_since_entry"] = float(pos["entry_price"])
                    LOG.warning(
                        "parent %s ended in %s with partial fill %d shares",
                        ticker, canonical, filled_qty,
                    )
                    emit_entry_fill(cfg, pos=pos, ev=ev)
                else:
                    open_positions.pop(ticker, None)
                    LOG.info("parent %s ended in %s — position dropped", ticker, canonical)
                    emit_order_event(cfg, pos=pos, role="parent_terminal", ev=ev)
                dirty = True
                events.append(ev)

        elif role in ("target", "stop") and pos is not None:
            # Item 8 (#6): use the same canonical-or-native filled
            # check as the parent branch. Translators that only
            # populate ``canonical_status`` would otherwise miss
            # child fills entirely.
            if status in _FILLED or canonical == "FILLED":
                pos.setdefault("filled_children", {})[role] = {
                    "filled_qty": filled_qty,
                    "filled_avg_price": filled_avg_f,
                }
                dirty = True
                events.append(ev)
                emit_order_event(cfg, pos=pos, role=role, ev=ev)

        elif role == "exit" and pos is not None:
            if status in _FILLED or canonical == "FILLED":
                pos["exit_fill_price"] = filled_avg_f
                pos["exit_filled_qty"] = filled_qty
                # Phase 3 will close the position on this signal.
                dirty = True
                events.append(ev)
                emit_order_event(cfg, pos=pos, role="exit", ev=ev)

    if dirty:
        save_state(state, state_path)

    return events


# ---------------------------------------------------------------- exits


# Allowed exit reasons (closure taxonomy).
EXIT_REASONS = {
    "stop_hit", "target_hit", "time_stop", "signal_fade",
    "kill_switch_l2", "kill_switch_l3", "closed_externally",
}


def trading_days_since(entry_iso: str, today_et: date) -> int:
    """Number of NYSE trading days between entry's ET date and today_et,
    counted as days *elapsed* (entry day = 0)."""
    entry_dt = datetime.fromisoformat(entry_iso.replace("Z", "+00:00"))
    entry_date = _to_eastern(entry_dt).date()
    if entry_date >= today_et:
        return 0
    sched = _NYSE.schedule(start_date=entry_date, end_date=today_et)
    if sched.empty:
        return 0
    # The schedule includes both entry_date and today_et; "elapsed
    # trading days" excludes the entry day itself.
    return max(0, len(sched) - 1)


def trigger_time_stop(
    ticker: str,
    pos: dict[str, Any],
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
    reason: str = "time_stop",
    time_in_force: str = "DAY",
) -> None:
    """Cancel both OCO children, submit a market sell, mark the position
    as exiting. Idempotent on cancel: a child already filled (404) is
    treated as success so the market sell still goes out."""
    LOG.info("Triggering exit (%s) for %s qty=%d",
             reason, ticker, pos.get("qty"))
    children = pos.get("child_order_ids") or {}
    for role in ("target", "stop"):
        oid = children.get(role)
        if not oid:
            continue
        try:
            cancel_order(oid, http, api_key)
        except Exception as e:
            LOG.warning("cancel %s child %s failed (continuing): %s",
                        ticker, role, e)
    venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
    try:
        resp = submit_market_sell(
            ticker, int(pos["qty"]), http, api_key,
            venue_code=venue_code, time_in_force=time_in_force,
        )
    except Exception as e:
        LOG.exception("market-sell submission failed for %s: %s", ticker, e)
        return

    # Item 7 fix: a 4xx/5xx from /api/v2/orders does NOT raise from
    # submit_market_sell — it returns a parsed body with
    # ``_http_status`` set. We must validate before mutating state.
    # The previous code blindly set status="exiting" with whatever
    # exit_id it could parse (often ""), stranding the position so
    # the next time-stop / signal-fade pass would skip it on
    # ``status != "filled"``.
    http_status = (resp or {}).get("_http_status") if isinstance(resp, dict) else None
    if http_status not in (200, 201):
        LOG.error(
            "market-sell rejected for %s (status=%s); leaving status='filled' "
            "so the next pass can retry: %s",
            ticker, http_status, resp,
        )
        return

    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    exit_id = data.get("order_id") or data.get("id") or ""
    if not exit_id:
        LOG.error(
            "market-sell accepted for %s but no order_id surfaced; "
            "leaving status='filled' so the next pass can retry: %s",
            ticker, resp,
        )
        return

    pos["status"] = "exiting"
    pos["exit_reason"] = reason
    pos["exit_order_id"] = exit_id
    pos["exit_submitted_at"] = datetime.now(timezone.utc).isoformat()
    if reason == "signal_fade":
        state.setdefault("pending_signal_fade_exits", {})[ticker] = {
            "submitted_at": pos["exit_submitted_at"],
            "exit_order_id": exit_id,
        }
    save_state(state, state_path)


def run_time_stop_pass(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    state_path: Path,
) -> list[str]:
    """Iterate filled positions; trigger time-stop when entry is
    ``max_hold_days`` trading days behind today. Returns the list of
    tickers that were time-stopped this pass."""
    max_hold = int(cfg["exits"]["max_hold_days"])
    out: list[str] = []
    open_positions = dict(state.get("open_positions") or {})
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        elapsed = trading_days_since(pos.get("entry_timestamp", ""), today_et)
        if elapsed >= max_hold:
            trigger_time_stop(
                ticker, pos, cfg, http, api_key,
                state=state, state_path=state_path,
                reason="time_stop", time_in_force="DAY",
            )
            out.append(ticker)
    return out


# ---------------------------------------------------------------- features
#
# DUPLICATION NOTE — feature math
#
# This is a deliberate copy of the prefilter's ``compute_features``
# scoped to a single ticker. We do NOT refactor the prefilter to share
# a feature module: the prefilter ships its own JSON contract and we
# pin parity via a regression test (see
# tests/strategies/test_bowaka_phase3.py:test_signal_fade_features_match_prefilter).
# Any future drift will break that test.


def compute_features_single(bars: pd.DataFrame, cfg: dict) -> dict[str, float]:
    """Single-ticker version of the prefilter's compute_features.

    ``bars`` is a DataFrame indexed by date (or with a ``timestamp`` /
    ``ts`` column) with lowercase OHLCV columns. Returns a dict with
    every gate-checked feature plus ``close``.
    """
    if bars.empty:
        return {}
    df = bars.copy()
    if "timestamp" not in df.columns:
        if df.index.name in ("timestamp", "ts", "date") or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
        elif "ts" in df.columns:
            df = df.rename(columns={"ts": "timestamp"})
    df = df.sort_values("timestamp").reset_index(drop=True)

    lookback = int(cfg["indicators"]["lookback_days"])
    atr_n = int(cfg["indicators"]["atr_days"])
    ema_n = int(cfg["indicators"]["ema_days"])
    slope_lb = int(cfg["indicators"]["ema_slope_lookback"])

    df["dollar_volume"] = df["close"] * df["volume"]
    df["avg_dollar_volume"] = df["dollar_volume"].shift(1).rolling(lookback).mean()
    df["avg_volume"] = df["volume"].shift(1).rolling(lookback).mean()
    df["rvol"] = df["volume"] / df["avg_volume"]

    df["prev_close"] = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"] - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(atr_n).mean()
    df["atr_pct"] = df["atr"] / df["close"]

    df["gap_pct"] = df["open"] / df["prev_close"] - 1.0
    df["range_expansion"] = (df["high"] - df["low"]) / df["atr"]

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = ((df["close"] - df["low"]) / rng).fillna(0.5)

    df["ema"] = df["close"].ewm(span=ema_n, adjust=False).mean()
    df["ema_distance"] = df["close"] / df["ema"] - 1.0
    df["ema_lagged"] = df["ema"].shift(slope_lb)
    df["ema_slope"] = df["ema"] / df["ema_lagged"] - 1.0

    last = df.iloc[-1]
    out = {}
    for k in ("close", "rvol", "atr_pct", "range_expansion",
              "close_location", "ema_distance", "ema_slope",
              "avg_dollar_volume", "gap_pct"):
        v = last.get(k)
        out[k] = float(v) if v is not None and not pd.isna(v) else None
    return out


def signal_passes_gates(features: dict[str, float | None], cfg: dict) -> bool:
    """All non-null gates from cfg.signal_gates must pass on the
    feature dict. A null gate is disabled (skipped)."""
    gates = cfg.get("signal_gates", {}) or {}
    spec = [
        ("rvol_min", "rvol"),
        ("atr_pct_min", "atr_pct"),
        ("range_expansion_min", "range_expansion"),
        ("close_location_min", "close_location"),
        ("ema_distance_min", "ema_distance"),
        ("ema_slope_min", "ema_slope"),
    ]
    for cfg_key, feat_key in spec:
        thr = gates.get(cfg_key)
        if thr is None:
            continue
        val = features.get(feat_key)
        if val is None or val < thr:
            return False
    return True


# ---------------------------------------------------------------- bars fetch


def fetch_daily_bars_for_signal_fade(
    ticker: str,
    venue_code: str,
    http: httpx.Client,
    api_key: str,
    *,
    lookback_calendar_days: int,
    end: datetime,
) -> pd.DataFrame:
    """POST /api/v2/bars for one ticker, daily timeframe, ~30 calendar
    days back. Returns a DataFrame ordered by timestamp ascending."""
    from datetime import timedelta as _td

    start = end - _td(days=lookback_calendar_days)
    body = {
        "apikey": api_key,
        "instrument": {"venue_code": venue_code, "canonical_symbol": ticker},
        "interval": "1d",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    r = http.post("/api/v2/bars",
                  json=body, headers=_api_headers(api_key))
    r.raise_for_status()
    payload = r.json().get("data") or {}
    rows = payload.get("bars") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ts" in df.columns:
        df["timestamp"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.drop(columns=["ts"])
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------- signal-fade


def run_signal_fade_pass(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    state_path: Path,
    now_utc: datetime,
) -> list[str]:
    """EOD subroutine. For each filled position, fetch its daily bars,
    re-run feature math, compare to the configured signal_gates, and
    submit a MOO sell (TIF=OPG) when any gate fails."""
    if state.get("signal_fade_evaluated_for_date") == today_et.isoformat():
        return []
    if not cfg.get("exits", {}).get("signal_fade_enabled", True):
        state["signal_fade_evaluated_for_date"] = today_et.isoformat()
        save_state(state, state_path)
        return []

    faded: list[str] = []
    open_positions = dict(state.get("open_positions") or {})
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
        try:
            bars = fetch_daily_bars_for_signal_fade(
                ticker, venue_code, http, api_key,
                lookback_calendar_days=45, end=now_utc,
            )
        except Exception as e:
            LOG.warning("signal_fade bars fetch failed for %s: %s — keeping position",
                        ticker, e)
            continue
        if bars.empty or len(bars) < int(cfg["indicators"]["lookback_days"]):
            LOG.info("signal_fade: insufficient bars for %s — keeping position",
                     ticker)
            continue
        feats = compute_features_single(bars, cfg)
        if not signal_passes_gates(feats, cfg):
            LOG.info("signal faded for %s: %s", ticker, feats)
            trigger_time_stop(
                ticker, pos, cfg, http, api_key,
                state=state, state_path=state_path,
                reason="signal_fade", time_in_force="OPG",
            )
            faded.append(ticker)

    state["signal_fade_evaluated_for_date"] = today_et.isoformat()
    save_state(state, state_path)
    return faded


# -------------------------------------------------------- daily marks (analytics)


def write_daily_marks(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    summary_path: Path,
    state_path: Path,
    now_utc: datetime,
) -> list[str]:
    """End-of-session analytic snapshot. For every filled position
    fetch today's daily bar, append a ``daily_mark`` record to the
    daily-summary jsonl, and update the position's
    ``peak_since_entry`` / ``trough_since_entry`` for MFE/MAE
    tracking.

    The record is purpose-built for offline tuning: it carries the
    day's OHLCV, the unrealized P&L at close, the running excursion,
    today's recomputed signal features, and which signal-fade gates
    passed/failed. Combined with the ``opened`` and ``closure``
    records, an analyst can reconstruct the full lifecycle of every
    trade and slice by signal regime, hold duration, gap-at-open,
    etc.

    Idempotent — once-per-day, deduped via
    ``state.daily_marks_written_for_date``. Returns the list of
    tickers that received a mark this call (empty when already
    written today or no filled positions exist).
    """
    today_iso = today_et.isoformat()
    if state.get("daily_marks_written_for_date") == today_iso:
        return []
    open_positions = dict(state.get("open_positions") or {})
    if not open_positions:
        # Nothing to mark, but still set the dedupe so a no-position
        # day doesn't re-attempt every tick.
        state["daily_marks_written_for_date"] = today_iso
        save_state(state, state_path)
        return []

    marked: list[str] = []
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        venue_code = pos.get("venue_code") or cfg["sizing"]["default_venue_code"]
        try:
            bars = fetch_daily_bars_for_signal_fade(
                ticker, venue_code, http, api_key,
                lookback_calendar_days=45, end=now_utc,
            )
        except Exception as e:
            LOG.warning(
                "daily_mark bars fetch failed for %s: %s — skipping today",
                ticker, e,
            )
            continue
        if bars.empty:
            LOG.warning("daily_mark: no bars for %s — skipping today", ticker)
            continue

        last = bars.iloc[-1]
        try:
            day_open = float(last.get("open"))
            day_high = float(last.get("high"))
            day_low = float(last.get("low"))
            day_close = float(last.get("close"))
            day_volume = float(last.get("volume"))
        except (TypeError, ValueError):
            LOG.warning(
                "daily_mark: bad bar shape for %s; skipping today", ticker,
            )
            continue

        # Update running peak/trough for MFE/MAE.
        entry_price_v = pos.get("entry_price")
        try:
            entry_price = float(entry_price_v) if entry_price_v is not None else None
        except (TypeError, ValueError):
            entry_price = None
        if entry_price is None or entry_price <= 0:
            LOG.warning(
                "daily_mark: %s has no entry_price yet (status=%s); "
                "writing mark without unrealized pnl",
                ticker, pos.get("status"),
            )
        prev_peak = pos.get("peak_since_entry")
        prev_trough = pos.get("trough_since_entry")
        try:
            prev_peak_f = float(prev_peak) if prev_peak is not None else None
            prev_trough_f = float(prev_trough) if prev_trough is not None else None
        except (TypeError, ValueError):
            prev_peak_f = prev_trough_f = None
        # Default both anchors to entry_price when missing (pre-this-
        # commit positions don't have them); subsequent passes update.
        if prev_peak_f is None and entry_price is not None:
            prev_peak_f = entry_price
        if prev_trough_f is None and entry_price is not None:
            prev_trough_f = entry_price
        new_peak = max(prev_peak_f, day_high) if prev_peak_f is not None else day_high
        new_trough = min(prev_trough_f, day_low) if prev_trough_f is not None else day_low
        pos["peak_since_entry"] = new_peak
        pos["trough_since_entry"] = new_trough

        qty = int(pos.get("qty") or 0)
        unrealized_pnl = (
            (day_close - entry_price) * qty
            if entry_price is not None else None
        )
        unrealized_pnl_pct = (
            (day_close - entry_price) / entry_price
            if entry_price is not None and entry_price > 0 else None
        )
        mfe_dollar = (
            (new_peak - entry_price) * qty
            if entry_price is not None and new_peak is not None else None
        )
        mae_dollar = (
            (new_trough - entry_price) * qty
            if entry_price is not None and new_trough is not None else None
        )

        # Days held since entry (NYSE trading days).
        entry_iso = pos.get("entry_timestamp") or ""
        try:
            days_held = trading_days_since(entry_iso, today_et) if entry_iso else None
        except Exception:
            days_held = None

        # Recompute today's signal features on the fresh bar window
        # so the analyst can see how the signal evolved relative to
        # entry. Skip when not enough history for the prefilter math.
        current_features: dict[str, float] | None = None
        signal_fade_gates: dict[str, dict[str, Any]] | None = None
        if len(bars) >= int(cfg["indicators"]["lookback_days"]):
            try:
                current_features = compute_features_single(bars, cfg)
                # Per-gate breakdown (matches signal_passes_gates).
                gates_cfg = cfg.get("signal_gates", {}) or {}
                spec = [
                    ("rvol_min", "rvol"),
                    ("atr_pct_min", "atr_pct"),
                    ("range_expansion_min", "range_expansion"),
                    ("close_location_min", "close_location"),
                    ("ema_distance_min", "ema_distance"),
                    ("ema_slope_min", "ema_slope"),
                ]
                signal_fade_gates = {}
                for cfg_key, feat_key in spec:
                    thr = gates_cfg.get(cfg_key)
                    val = current_features.get(feat_key)
                    if thr is None:
                        signal_fade_gates[feat_key] = {
                            "value": val, "threshold": None, "passed": True,
                        }
                    else:
                        signal_fade_gates[feat_key] = {
                            "value": val,
                            "threshold": thr,
                            "passed": val is not None and val >= thr,
                        }
            except Exception as e:
                LOG.warning(
                    "daily_mark: feature recompute failed for %s: %s", ticker, e,
                )

        record = {
            "record_type": "daily_mark",
            "ticker": ticker,
            "session_date": today_iso,
            "days_held": days_held,
            "open": day_open,
            "high": day_high,
            "low": day_low,
            "mark_price": day_close,
            "volume": day_volume,
            "qty": qty,
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "peak_since_entry": new_peak,
            "trough_since_entry": new_trough,
            "mfe_dollar": mfe_dollar,
            "mae_dollar": mae_dollar,
            "target_price": pos.get("target_price"),
            "stop_price": pos.get("stop_price"),
            "current_features": current_features,
            "signal_fade_gates": signal_fade_gates,
            "venue_code": pos.get("venue_code"),
            "exchange": pos.get("exchange"),
            "link_id": pos.get("link_id"),
        }
        try:
            append_closure_record(summary_path, record)
        except Exception as e:
            LOG.exception(
                "could not append daily_mark for %s: %s", ticker, e,
            )
            continue
        marked.append(ticker)
        LOG.info(
            "daily_mark %s d=%s close=%.4f unrealized=%s peak=%.4f trough=%.4f",
            ticker, days_held, day_close,
            f"{unrealized_pnl:.2f}" if unrealized_pnl is not None else "?",
            new_peak, new_trough,
        )

    state["daily_marks_written_for_date"] = today_iso
    save_state(state, state_path)
    return marked


# ---------------------------------------------------------------- closures


def append_closure_record(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON-Lines record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()


# -------------------------------------------------------- per-trade rich logging
#
# One file per buy, named by link_id. Lives at
#   <daily_summary_path.parent>/trades/<link_id>.jsonl
# Each file is JSONL append-only and carries the full lifecycle of one
# position: entry_decision -> parent_submitted -> entry_fill ->
# bracket_attached -> intraday_tick (many) -> order_event* ->
# exit. Cross-trade analysis stays in daily_summary.jsonl.


def _trade_log_path(cfg: dict, link_id: str) -> Path | None:
    """Per-trade jsonl path. Sibling ``trades/`` dir under the daily-
    summary path's parent. Returns None when link_id is missing
    (defensive — old states without link_id just skip the rich log)."""
    if not link_id:
        return None
    summary_path = _resolve_path(cfg, "daily_summary_path")
    return summary_path.parent / "trades" / f"{link_id}.jsonl"


def _append_trade_log(cfg: dict | None, link_id: str | None, record: dict[str, Any]) -> None:
    """Append a single record to the per-trade jsonl. Best-effort —
    a write failure does NOT propagate; logging is observability,
    not an order-flow blocker. ``cfg=None`` is a no-op so call sites
    without cfg threading (older tests, ad-hoc utilities) can invoke
    emit_* without scaffolding."""
    if cfg is None:
        return
    path = _trade_log_path(cfg, link_id or "")
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
    except Exception as e:
        LOG.warning("trade-log append failed (link_id=%s): %s", link_id, e)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- emit_* helpers: each call writes one record to the per-trade jsonl


def emit_entry_decision(
    cfg: dict,
    *,
    link_id: str,
    entry: "Entry",
    state: State,
    slot_index: int,
    slate_size: int,
    running_gross_at_entry: float,
    binding_cap: str,
    target_dollars: float,
    adv_cap_dollars: float | None,
    intraday_confirmation_passed: bool | None,
) -> None:
    """At submit time: capture every variable the analyst would want
    to know about why we picked this name at this moment.

    Per-gate breakdown for signal_gates so a quant can bucket entries
    by which gate was the marginal pass. Sizing rationale flags the
    binding cap (per_trade_pct vs max_per_trade_dollars vs adv_cap).
    Selection slot index lets you study slate-position vs realized PnL.
    """
    cand = entry.candidate
    feats = dict(cand.features or {})
    gates_cfg = cfg.get("signal_gates", {}) or {}
    spec = [
        ("rvol_min", "rvol"),
        ("atr_pct_min", "atr_pct"),
        ("range_expansion_min", "range_expansion"),
        ("close_location_min", "close_location"),
        ("ema_distance_min", "ema_distance"),
        ("ema_slope_min", "ema_slope"),
    ]
    gates_breakdown = {}
    for cfg_key, feat_key in spec:
        thr = gates_cfg.get(cfg_key)
        val = feats.get(feat_key)
        gates_breakdown[feat_key] = {
            "value": _safe_float(val),
            "threshold": _safe_float(thr) if thr is not None else None,
            "passed": (
                True if thr is None
                else (val is not None and float(val) >= float(thr))
            ),
        }

    sizing_cfg = cfg.get("sizing", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}
    exits_cfg = cfg.get("exits", {}) or {}
    entry_cfg = cfg.get("entry", {}) or {}

    rec = {
        "record_type": "entry_decision",
        "ts": _now_utc_iso(),
        "ticker": entry.ticker,
        "link_id": link_id,
        "venue_code": entry.venue_code,
        "exchange": cand.exchange,
        "candidate": {
            "close": entry.close_price,
            "signal_strength": cand.signal_strength,
            "features": feats,
        },
        "gates": gates_breakdown,
        "selection": {
            "slot_index": slot_index,
            "slate_size": slate_size,
            "max_concurrent_positions": int(sizing_cfg.get("max_concurrent_positions") or 0),
            "running_gross_at_entry": running_gross_at_entry,
            "max_gross_exposure_pct": _safe_float(risk_cfg.get("max_gross_exposure_pct")),
            "max_gross_exposure_dollars": _safe_float(risk_cfg.get("max_gross_exposure_dollars")),
        },
        "sizing": {
            "qty": entry.qty,
            "candidate_close": entry.close_price,
            "notional_at_close": entry.qty * entry.close_price,
            "equity_at_entry": _safe_float(entry.equity_at_entry),
            "per_trade_pct": _safe_float(sizing_cfg.get("per_trade_pct")),
            "max_per_trade_dollars": _safe_float(risk_cfg.get("max_per_trade_dollars")),
            "max_position_as_adv_frac": _safe_float(risk_cfg.get("max_position_as_adv_frac")),
            "avg_dollar_volume": _safe_float(feats.get("avg_dollar_volume")),
            "adv_cap_dollars": _safe_float(adv_cap_dollars),
            "target_dollars": _safe_float(target_dollars),
            "binding_cap": binding_cap,
        },
        "bracket": {
            "mode": entry_cfg.get("bracket_pricing_mode") or "actual_fill",
            "target_pct": _safe_float(exits_cfg.get("target_pct")),
            "stop_pct": _safe_float(exits_cfg.get("stop_pct")),
            "max_hold_days": int(exits_cfg.get("max_hold_days") or 0),
            "signal_fade_enabled": bool(exits_cfg.get("signal_fade_enabled", True)),
        },
        "risk": {
            "daily_loss_pct": _safe_float(risk_cfg.get("daily_loss_pct")),
            "daily_pnl_baseline_equity": _safe_float(state.get("daily_pnl_baseline_equity")),
            "daily_pnl_tripped": bool(state.get("daily_pnl_tripped", False)),
        },
        "intraday_confirmation": {
            "enabled": bool((entry_cfg.get("intraday_confirmation") or {}).get("enabled")),
            "passed": intraday_confirmation_passed,
        },
        "config_hash": config_hash(cfg),
    }
    _append_trade_log(cfg, link_id, rec)


def emit_parent_submitted(
    cfg: dict, *, link_id: str, ticker: str, parent_id: str,
    qty: int, venue_code: str, http_status: int,
) -> None:
    _append_trade_log(cfg, link_id, {
        "record_type": "parent_submitted",
        "ts": _now_utc_iso(),
        "ticker": ticker, "link_id": link_id,
        "parent_order_id": parent_id,
        "qty": qty, "venue_code": venue_code,
        "http_status": http_status,
    })


def emit_entry_fill(
    cfg: dict, *, pos: dict[str, Any], ev: "FillEvent",
) -> None:
    link_id = pos.get("link_id") or ""
    candidate_close = _safe_float(pos.get("candidate_close"))
    fill_price = _safe_float(ev.filled_avg_price)
    slippage_pct = (
        (fill_price - candidate_close) / candidate_close
        if (fill_price is not None and candidate_close and candidate_close > 0)
        else None
    )
    submitted_at = pos.get("entry_timestamp")
    fill_latency_s = None
    if submitted_at:
        try:
            sub_dt = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
            fill_latency_s = (datetime.now(timezone.utc) - sub_dt).total_seconds()
        except Exception:
            pass
    _append_trade_log(cfg, link_id, {
        "record_type": "entry_fill",
        "ts": _now_utc_iso(),
        "ticker": ev.ticker, "link_id": link_id,
        "parent_order_id": ev.order_id,
        "filled_qty": ev.filled_qty,
        "filled_avg_price": fill_price,
        "candidate_close": candidate_close,
        "slippage_vs_candidate_close_pct": slippage_pct,
        "fill_latency_seconds": fill_latency_s,
        "partial_fill": (
            ev.filled_qty > 0 and ev.filled_qty < int(pos.get("qty") or 0)
        ),
    })


def emit_bracket_attached(
    cfg: dict, *, pos: dict[str, Any], target_id: str, stop_id: str,
    target_price: float, stop_price: float,
) -> None:
    link_id = pos.get("link_id") or ""
    fill_price = _safe_float(pos.get("entry_price"))
    _append_trade_log(cfg, link_id, {
        "record_type": "bracket_attached",
        "ts": _now_utc_iso(),
        "ticker": link_id.split("-")[1] if "-" in link_id else "?",
        "link_id": link_id,
        "target_order_id": target_id, "stop_order_id": stop_id,
        "target_price": target_price, "stop_price": stop_price,
        "fill_price": fill_price,
        "target_pct": _safe_float(pos.get("target_pct")),
        "stop_pct": _safe_float(pos.get("stop_pct")),
        "computed_target_check": (
            round(fill_price * (1 + float(pos.get("target_pct"))), 2)
            if fill_price is not None and pos.get("target_pct") is not None
            else None
        ),
        "computed_stop_check": (
            round(fill_price * (1 - float(pos.get("stop_pct"))), 2)
            if fill_price is not None and pos.get("stop_pct") is not None
            else None
        ),
    })


def emit_order_event(
    cfg: dict, *, pos: dict[str, Any], role: str, ev: "FillEvent",
) -> None:
    """Non-terminal order events (child fills don't go here when they
    cause closure; the closure record covers those). Use this for
    intermediate state changes the analyst might want to inspect."""
    link_id = pos.get("link_id") or ""
    _append_trade_log(cfg, link_id, {
        "record_type": "order_event",
        "ts": _now_utc_iso(),
        "ticker": ev.ticker, "link_id": link_id,
        "role": role,
        "order_id": ev.order_id,
        "status": ev.status,
        "filled_qty": ev.filled_qty,
        "filled_avg_price": _safe_float(ev.filled_avg_price),
    })


def emit_intraday_tick(
    cfg: dict, *, pos: dict[str, Any], ticker: str,
    quote: dict[str, Any], now_utc: datetime,
    session_end_utc: datetime | None = None,
) -> None:
    """One snapshot per minute per held position. Captures the quote
    state, the position's running P&L + excursion, distance to
    target/stop, and time-in-trade indicators."""
    link_id = pos.get("link_id") or ""
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    last = _safe_float(quote.get("last"))
    bid_size = _safe_float(quote.get("bid_size"))
    ask_size = _safe_float(quote.get("ask_size"))
    mid = (bid + ask) / 2.0 if (bid and ask and ask > bid) else None
    spread = (ask - bid) if (bid and ask) else None
    spread_pct = (spread / mid) if (spread is not None and mid and mid > 0) else None

    metadata = quote.get("metadata") or {}
    day_open = _safe_float(metadata.get("open"))
    day_high = _safe_float(metadata.get("high"))
    day_low = _safe_float(metadata.get("low"))
    day_close = _safe_float(metadata.get("close"))
    day_volume = _safe_float(metadata.get("volume"))
    prev_close = _safe_float(metadata.get("prev_close"))

    entry_price = _safe_float(pos.get("entry_price"))
    qty = int(pos.get("qty") or 0)
    target_price = _safe_float(pos.get("target_price"))
    stop_price = _safe_float(pos.get("stop_price"))
    # Use mid for P&L calc; fall back to last when only one side has a quote.
    mark = mid if mid is not None else last
    unrealized_pnl = (
        (mark - entry_price) * qty
        if (mark is not None and entry_price is not None) else None
    )
    unrealized_pnl_pct = (
        (mark - entry_price) / entry_price
        if (mark is not None and entry_price is not None and entry_price > 0)
        else None
    )

    # Update peak/trough on the live mark — finer-grained than the
    # daily mark. The daily_mark function still updates from day's
    # high/low at session end so the offline analyst can cross-check.
    prev_peak = _safe_float(pos.get("peak_since_entry")) or entry_price
    prev_trough = _safe_float(pos.get("trough_since_entry")) or entry_price
    new_peak = max(prev_peak, mark) if (prev_peak is not None and mark is not None) else (prev_peak or mark)
    new_trough = min(prev_trough, mark) if (prev_trough is not None and mark is not None) else (prev_trough or mark)
    if new_peak is not None:
        pos["peak_since_entry"] = new_peak
    if new_trough is not None:
        pos["trough_since_entry"] = new_trough
    mfe_dollar = (
        (new_peak - entry_price) * qty
        if (new_peak is not None and entry_price is not None) else None
    )
    mae_dollar = (
        (new_trough - entry_price) * qty
        if (new_trough is not None and entry_price is not None) else None
    )
    drawdown_from_peak_pct = (
        (mark - new_peak) / new_peak
        if (mark is not None and new_peak and new_peak > 0)
        else None
    )
    runup_from_trough_pct = (
        (mark - new_trough) / new_trough
        if (mark is not None and new_trough and new_trough > 0)
        else None
    )

    distance_to_target_pct = (
        (target_price - mark) / mark
        if (target_price is not None and mark and mark > 0)
        else None
    )
    distance_to_stop_pct = (
        (stop_price - mark) / mark
        if (stop_price is not None and mark and mark > 0)
        else None
    )
    target_to_stop_ratio = (
        (distance_to_target_pct / abs(distance_to_stop_pct))
        if (distance_to_target_pct is not None
            and distance_to_stop_pct not in (None, 0))
        else None
    )

    # Time-in-trade.
    entry_iso = pos.get("entry_timestamp")
    minutes_held = None
    if entry_iso:
        try:
            sub_dt = datetime.fromisoformat(entry_iso.replace("Z", "+00:00"))
            minutes_held = int((now_utc - sub_dt).total_seconds() / 60)
        except Exception:
            pass
    session_minutes_remaining = None
    if session_end_utc is not None:
        session_minutes_remaining = int(
            max(0, (session_end_utc - now_utc).total_seconds() / 60)
        )

    rec = {
        "record_type": "intraday_tick",
        "ts": _now_utc_iso(),
        "ticker": ticker,
        "link_id": link_id,
        "quote": {
            "bid": bid, "ask": ask, "mid": mid,
            "spread": spread, "spread_pct": spread_pct,
            "bid_size": bid_size, "ask_size": ask_size,
            "last": last,
            "ts": quote.get("timestamp"),
        },
        "session_bar": {
            "open": day_open, "high": day_high, "low": day_low,
            "close": day_close, "volume": day_volume,
            "prev_close": prev_close,
            "gap_from_prev_close_pct": (
                (day_open - prev_close) / prev_close
                if (day_open is not None and prev_close and prev_close > 0)
                else None
            ),
            "intraday_range_pct": (
                (day_high - day_low) / day_open
                if (day_high is not None and day_low is not None
                    and day_open and day_open > 0)
                else None
            ),
        },
        "position": {
            "qty": qty,
            "entry_price": entry_price,
            "mark": mark,
            "current_value": (mark * qty) if (mark is not None) else None,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "target_price": target_price,
            "stop_price": stop_price,
        },
        "excursion": {
            "peak_since_entry": new_peak,
            "trough_since_entry": new_trough,
            "mfe_dollar": mfe_dollar,
            "mae_dollar": mae_dollar,
            "drawdown_from_peak_pct": drawdown_from_peak_pct,
            "runup_from_trough_pct": runup_from_trough_pct,
        },
        "distance": {
            "to_target_pct": distance_to_target_pct,
            "to_stop_pct": distance_to_stop_pct,
            "target_to_stop_ratio": target_to_stop_ratio,
        },
        "time": {
            "minutes_held": minutes_held,
            "session_minutes_remaining": session_minutes_remaining,
            "entry_timestamp": entry_iso,
        },
    }
    _append_trade_log(cfg, link_id, rec)


def emit_exit(
    cfg: dict, *, pos: dict[str, Any], closure_record: dict[str, Any],
) -> None:
    """Closure twin to the daily_summary closure record. Carries the
    entry_decision-equivalent context plus everything the analyst
    needs about the exit (slippage, hold duration, MFE/MAE)."""
    link_id = pos.get("link_id") or ""
    rec = dict(closure_record)
    rec["record_type"] = "exit"
    rec["ts"] = rec.get("exit_timestamp") or _now_utc_iso()
    _append_trade_log(cfg, link_id, rec)


# ---- intraday tick loop


def _fetch_quotes_batch(
    instruments: list[tuple[str, str]],
    http: httpx.Client,
    api_key: str,
) -> dict[str, dict[str, Any]]:
    """POST /api/v2/quotes with multiple instruments. Returns a dict
    keyed by canonical_symbol. Empty / failure → empty dict (caller
    skips the tick log for missing tickers)."""
    if not instruments:
        return {}
    body = {
        "apikey": api_key,
        "instruments": [
            {"venue_code": v, "canonical_symbol": s} for s, v in instruments
        ],
    }
    try:
        r = http.post("/api/v2/quotes", json=body, headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.warning("intraday quote batch fetch failed: %s", e)
        return {}
    if r.status_code != 200:
        LOG.warning(
            "intraday quote batch HTTP %d: %s",
            r.status_code, (r.text or "")[:200],
        )
        return {}
    try:
        rows = r.json().get("data") or []
    except ValueError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = (row or {}).get("instrument", {}).get("canonical_symbol")
        q = (row or {}).get("quote") or {}
        if sym:
            out[sym] = q
    return out


def run_intraday_tick_logging(
    cfg: dict,
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    now_utc: datetime,
    interval_seconds: int = 60,
) -> list[str]:
    """Once per main-loop tick: log a per-position quote snapshot if
    at least ``interval_seconds`` have elapsed since that position's
    last tick. Mutates pos.last_tick_logged_at + pos.peak/trough_since
    in place. Returns the list of tickers logged this call."""
    open_positions = state.get("open_positions") or {}
    due: list[tuple[str, str]] = []  # (symbol, venue)
    for ticker, pos in open_positions.items():
        if pos.get("status") != "filled":
            continue
        last_iso = pos.get("last_tick_logged_at")
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                if (now_utc - last_dt).total_seconds() < interval_seconds:
                    continue
            except Exception:
                pass
        due.append((
            ticker,
            pos.get("venue_code") or cfg["sizing"]["default_venue_code"],
        ))
    if not due:
        return []

    quotes = _fetch_quotes_batch(due, http, api_key)
    if not quotes:
        return []

    logged: list[str] = []
    # Compute today's session-end UTC for "minutes remaining" — used
    # in the tick payload. Falls back to None when the cfg session
    # block isn't loadable.
    session_end_utc: datetime | None = None
    try:
        import pytz
        session_end_str = (cfg.get("session") or {}).get("end") or "15:55"
        h, m = (int(p) for p in session_end_str.split(":")[:2])
        et = pytz.timezone((cfg.get("session") or {}).get("timezone") or "America/New_York")
        today_et = _to_eastern(now_utc).date()
        session_end_utc = et.localize(
            datetime.combine(today_et, _dtime(h, m))
        ).astimezone(timezone.utc)
    except Exception:
        session_end_utc = None

    dirty = False
    for ticker, _venue in due:
        q = quotes.get(ticker)
        if q is None:
            continue
        pos = open_positions.get(ticker)
        if pos is None:
            continue
        try:
            emit_intraday_tick(
                cfg, pos=pos, ticker=ticker, quote=q,
                now_utc=now_utc, session_end_utc=session_end_utc,
            )
            pos["last_tick_logged_at"] = now_utc.isoformat()
            dirty = True
            logged.append(ticker)
        except Exception as e:
            LOG.warning("emit_intraday_tick failed for %s: %s", ticker, e)
    if dirty:
        save_state(state, state_path)
    return logged


def close_position(
    ticker: str,
    state: State,
    cfg: dict,
    *,
    state_path: Path,
    summary_path: Path,
    exit_price: float,
    reason: str,
) -> dict[str, Any]:
    """Compute realized PnL, append jsonl, drop from state.

    The closure record carries the analytic-enrichment fields the
    operator uses to tune target_pct / stop_pct / max_hold_days /
    signal_gates: hold duration, max-favorable / max-adverse
    excursion, peak / trough since entry, plus the entry features.
    """
    pos = (state.get("open_positions") or {}).get(ticker)
    if pos is None:
        return {}
    entry_price = float(pos.get("entry_price") or 0.0)
    qty = int(pos.get("qty") or 0)
    realized = (exit_price - entry_price) * qty
    entry_iso = pos.get("entry_timestamp")
    exit_iso = datetime.now(timezone.utc).isoformat()
    # Hold duration in NYSE trading days. Falls back to None when
    # entry_timestamp is missing (very old states).
    hold_trading_days: int | None = None
    if entry_iso:
        try:
            today_et = _to_eastern(datetime.now(timezone.utc)).date()
            hold_trading_days = trading_days_since(entry_iso, today_et)
        except Exception:
            hold_trading_days = None
    entry_to_exit_pct = (
        (exit_price - entry_price) / entry_price
        if entry_price > 0 else None
    )
    peak = pos.get("peak_since_entry")
    trough = pos.get("trough_since_entry")
    try:
        peak_f = float(peak) if peak is not None else None
        trough_f = float(trough) if trough is not None else None
    except (TypeError, ValueError):
        peak_f = trough_f = None
    mfe_dollar = (peak_f - entry_price) * qty if (peak_f is not None and entry_price > 0) else None
    mae_dollar = (trough_f - entry_price) * qty if (trough_f is not None and entry_price > 0) else None
    mfe_pct = (peak_f - entry_price) / entry_price if (peak_f is not None and entry_price > 0) else None
    mae_pct = (trough_f - entry_price) / entry_price if (trough_f is not None and entry_price > 0) else None

    record = {
        "record_type": "closure",
        "ticker": ticker,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_timestamp": entry_iso,
        "exit_timestamp": exit_iso,
        "realized_pnl": realized,
        "reason": reason,
        "entry_features": pos.get("entry_features", {}),
        "venue_code": pos.get("venue_code"),
        "exchange": pos.get("exchange"),
        "signal_strength": pos.get("signal_strength"),
        "candidate_close": pos.get("candidate_close"),
        "target_pct": pos.get("target_pct"),
        "stop_pct": pos.get("stop_pct"),
        "target_price": pos.get("target_price"),
        "stop_price": pos.get("stop_price"),
        "bracket_pricing_mode": pos.get("bracket_pricing_mode"),
        "hold_trading_days": hold_trading_days,
        "entry_to_exit_pct": entry_to_exit_pct,
        "peak_since_entry": peak_f,
        "trough_since_entry": trough_f,
        "mfe_dollar": mfe_dollar,
        "mae_dollar": mae_dollar,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "link_id": pos.get("link_id"),
    }
    append_closure_record(summary_path, record)
    # Per-trade rich log: write the exit record under the same
    # link_id BEFORE we drop pos from state.
    emit_exit(cfg, pos=pos, closure_record=record)
    state["open_positions"].pop(ticker, None)
    state.get("pending_signal_fade_exits", {}).pop(ticker, None)
    save_state(state, state_path)
    LOG.info("closed %s: %s pnl=%.2f hold=%s mfe=%s mae=%s",
             ticker, reason, realized, hold_trading_days, mfe_dollar, mae_dollar)
    return record


def process_fill_events_for_closures(
    events: list[FillEvent],
    state: State,
    cfg: dict,
    *,
    state_path: Path,
    summary_path: Path,
) -> list[dict[str, Any]]:
    """Map fill events to closures based on which child filled.

    - parent filled        → ``opened`` jsonl record (Item 8 #8) so
                              write_session_summary's count_opened
                              reflects today's actual entries
    - target child filled  → ``target_hit``
    - stop child filled    → ``stop_hit``
    - exit_order_id filled → use the recorded exit reason
                              (time_stop / signal_fade)
    """
    out: list[dict[str, Any]] = []
    open_positions = state.get("open_positions") or {}
    for ev in events:
        pos = open_positions.get(ev.ticker)
        if pos is None:
            continue
        if ev.role == "parent" and ev.status == "FILLED":
            # Append an opened record so the daily summary's
            # count_opened counts trades that *opened today*, not
            # "positions still open at session end". A round-trip
            # (open + close intraday) writes one opened + one closure
            # → count_opened=1, count_closed=1, both correct.
            entry_iso = (
                pos.get("entry_timestamp")
                or datetime.now(timezone.utc).isoformat()
            )
            entry_price = float(ev.filled_avg_price or 0.0)
            qty = int(pos.get("qty") or ev.filled_qty or 0)
            notional = entry_price * qty if entry_price > 0 else None
            equity_at_entry = pos.get("equity_at_entry")
            try:
                equity_at_entry = float(equity_at_entry) if equity_at_entry is not None else None
            except (TypeError, ValueError):
                equity_at_entry = None
            notional_pct_of_equity = (
                (notional / equity_at_entry)
                if (notional is not None and equity_at_entry and equity_at_entry > 0)
                else None
            )
            candidate_close = pos.get("candidate_close")
            try:
                candidate_close = float(candidate_close) if candidate_close is not None else None
            except (TypeError, ValueError):
                candidate_close = None
            gap_at_open_pct = (
                ((entry_price - candidate_close) / candidate_close)
                if (candidate_close and candidate_close > 0 and entry_price > 0)
                else None
            )
            ic_cfg = _intraday_confirmation_cfg(cfg) if "_intraday_confirmation_cfg" in globals() else {}
            try:
                append_closure_record(summary_path, {
                    "record_type": "opened",
                    "ticker": ev.ticker,
                    "qty": qty,
                    "entry_price": entry_price,
                    "entry_timestamp": entry_iso,
                    "venue_code": pos.get("venue_code"),
                    "exchange": pos.get("exchange"),
                    "entry_features": pos.get("entry_features", {}),
                    "link_id": pos.get("link_id"),
                    # --- Item-(post-9) analytic enrichment ---
                    "signal_strength": pos.get("signal_strength"),
                    "candidate_close": candidate_close,
                    "gap_at_open_pct": gap_at_open_pct,
                    "target_pct": pos.get("target_pct"),
                    "stop_pct": pos.get("stop_pct"),
                    "target_price": pos.get("target_price"),
                    "stop_price": pos.get("stop_price"),
                    "bracket_pricing_mode": pos.get("bracket_pricing_mode"),
                    "equity_at_entry": equity_at_entry,
                    "notional": notional,
                    "notional_pct_of_equity": notional_pct_of_equity,
                    "intraday_confirmation_enabled": bool(ic_cfg.get("enabled")) if ic_cfg else False,
                })
            except Exception as e:
                LOG.exception(
                    "could not append opened record for %s: %s", ev.ticker, e,
                )
            # Don't `continue` — fall through so a parent fill that
            # also coincides with a close (rare) still gets handled
            # below. Currently no other branch matches role="parent"
            # so this is a no-op, but the structure is forgiving.
        if ev.role == "target" and ev.status in {"FILLED"}:
            price = ev.filled_avg_price or pos.get("target_price") or 0.0
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason="target_hit",
            ))
        elif ev.role == "stop" and ev.status in {"FILLED"}:
            price = ev.filled_avg_price or pos.get("stop_price") or 0.0
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason="stop_hit",
            ))
        elif ev.role == "exit" and ev.status in {"FILLED"}:
            reason = pos.get("exit_reason") or "time_stop"
            price = ev.filled_avg_price or pos.get("exit_fill_price") or 0.0
            out.append(close_position(
                ev.ticker, state, cfg,
                state_path=state_path, summary_path=summary_path,
                exit_price=float(price), reason=reason,
            ))
    return out


# ---------------------------------------------------------------- daily P&L


def update_daily_pnl(
    state: State,
    current_equity: float,
    cfg: dict,
    *,
    state_path: Path,
) -> bool:
    """Compare current equity to the session baseline. Trip the daily
    loss circuit breaker once, log the trip ratios. Returns True if
    the trip happened on this call."""
    baseline = state.get("daily_pnl_baseline_equity")
    if baseline in (None, 0):
        return False
    if state.get("daily_pnl_tripped"):
        return False
    pnl_pct = (current_equity - float(baseline)) / float(baseline)
    threshold = float(cfg["risk"]["daily_loss_pct"])
    if pnl_pct <= -threshold:
        state["daily_pnl_tripped"] = True
        save_state(state, state_path)
        LOG.error(
            "DAILY P&L CIRCUIT BREAKER tripped: pnl=%.4f baseline=%.2f current=%.2f threshold=-%.4f",
            pnl_pct, baseline, current_equity, threshold,
        )
        return True
    return False


# ---------------------------------------------------------------- halt detection


_HALT_STATUSES = {"held", "HELD", "pending_review", "PENDING_REVIEW"}


def _is_halt_signal(row: dict[str, Any]) -> bool:
    status = (row.get("native_status") or row.get("status") or "")
    if status in _HALT_STATUSES:
        return True
    canonical = (row.get("canonical_status") or "").upper()
    if canonical in {"HELD", "PENDING_REVIEW"}:
        return True
    reject = (row.get("reject_reason") or row.get("reject_reasons") or "").lower()
    return "halt" in reject


# ---------------------------------------------------------------- positions / orders fetch


def fetch_open_orders(http: httpx.Client, api_key: str, status="open") -> list[dict]:
    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"apikey": api_key, "status": status})
    r.raise_for_status()
    return r.json().get("data", {}).get("orders", []) or []


def fetch_positions(http: httpx.Client, api_key: str) -> list[dict]:
    r = http.get("/api/v2/positions",
                 headers=_api_headers(api_key),
                 params={"apikey": api_key})
    r.raise_for_status()
    return r.json().get("data", {}).get("positions", []) or []


# ---------------------------------------------------------------- reconciliation


def reconcile_at_startup(
    state: State,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    """Bring state in line with broker reality. Runs once before the
    main loop. Returns a summary dict for logging.

    Item 6 fix: even when local state is empty we still fetch broker
    positions so an untracked broker position (e.g., user moved
    state.json aside, deployed a fresh checkout, or the strategy
    crashed mid-entry) surfaces as an ``untracked`` warning. Previously
    the function returned early on empty state and silently never
    looked at the broker — directly contradicting the runbook claim
    that fresh state surfaces untracked broker positions.
    """
    summary = {
        "qty_corrected": [], "closed_externally": [], "untracked": [],
        "child_status_corrected": [], "pending_signal_fade_resolved": [],
    }
    open_positions = state.get("open_positions") or {}
    pending_signal_fade = state.get("pending_signal_fade_exits") or {}

    try:
        broker_positions = fetch_positions(http, api_key)
    except Exception as e:
        LOG.exception("reconcile: positions fetch failed: %s", e)
        return summary
    try:
        broker_open_orders = fetch_open_orders(http, api_key, status="open")
        broker_all_orders = fetch_open_orders(http, api_key, status="all")
    except Exception as e:
        LOG.exception("reconcile: orders fetch failed: %s", e)
        return summary

    # Empty local state but no broker positions either → genuine
    # fresh start. Log and return after the broker check completed.
    if not open_positions and not pending_signal_fade and not broker_positions:
        LOG.info("reconciliation: empty state + no broker positions; fresh start")
        return summary

    # Position keys vary by adapter — try canonical_symbol first.
    broker_pos_by_ticker: dict[str, dict] = {}
    for p in broker_positions:
        key = p.get("canonical_symbol") or p.get("symbol") or p.get("ticker")
        if key:
            broker_pos_by_ticker[key] = p

    for ticker, pos in list(open_positions.items()):
        if ticker not in broker_pos_by_ticker:
            # Position vanished externally — synthesize a closure.
            entry_price = float(pos.get("entry_price") or 0.0)
            qty = int(pos.get("qty") or 0)
            record = {
                "record_type": "closure",
                "ticker": ticker, "qty": qty,
                "entry_price": entry_price,
                "exit_price": entry_price,  # best effort
                "entry_timestamp": pos.get("entry_timestamp"),
                "exit_timestamp": datetime.now(timezone.utc).isoformat(),
                "realized_pnl": 0.0,
                "reason": "closed_externally",
                "entry_features": pos.get("entry_features", {}),
            }
            append_closure_record(summary_path, record)
            open_positions.pop(ticker, None)
            summary["closed_externally"].append(ticker)
            LOG.warning("reconcile: %s closed externally — recording synthetic closure", ticker)
            continue

        bp = broker_pos_by_ticker[ticker]
        try:
            broker_qty = int(float(bp.get("quantity") or bp.get("qty") or 0))
        except (TypeError, ValueError):
            broker_qty = 0
        if broker_qty != int(pos.get("qty") or 0):
            LOG.warning("reconcile: %s qty %d -> %d", ticker, pos["qty"], broker_qty)
            pos["qty"] = broker_qty
            summary["qty_corrected"].append(ticker)

    for ticker, bp in broker_pos_by_ticker.items():
        if ticker not in open_positions:
            LOG.warning("reconcile: untracked broker position: %s qty %s",
                        ticker, bp.get("quantity") or bp.get("qty"))
            summary["untracked"].append(ticker)

    # Child order status sync.
    open_order_ids = {o.get("id") or o.get("order_id") for o in broker_open_orders}
    all_orders_by_id = {
        (o.get("id") or o.get("order_id")): o for o in broker_all_orders
    }
    # Statuses that mean the child is gone for good — DAY-TIF OCO
    # children expire as ``canceled`` at session close; rejected /
    # expired / replaced are also non-recoverable. When we see one
    # of these we clear the role's ID from child_order_ids so
    # :func:`submit_pending_oco_children` re-attaches a fresh OCO
    # bracket on the next tick. The position would otherwise sit
    # naked overnight.
    _TERMINAL_CHILD = {
        "canceled", "cancelled", "rejected", "expired", "replaced",
        "done_for_day",
    }
    cleared_for_rebracket: set[str] = set()
    for ticker, pos in open_positions.items():
        children = pos.get("child_order_ids") or {}
        for role, oid in dict(children).items():
            if not oid or oid in open_order_ids:
                continue
            broker_view = all_orders_by_id.get(oid, {})
            native = (broker_view.get("native_status")
                      or broker_view.get("status") or "").lower()
            if not native:
                continue
            pos.setdefault("child_status_at_recon", {})[role] = native
            summary["child_status_corrected"].append(f"{ticker}:{role}={native}")
            if native in _TERMINAL_CHILD:
                # Clear the slot so submit_pending_oco_children sees
                # an actual_fill position with empty children and
                # re-brackets. Only fires for actual_fill-mode
                # positions; legacy candidate_close positions are
                # untouched (their bracket was atomic with the parent).
                if pos.get("bracket_pricing_mode") == "actual_fill" and pos.get("status") == "filled":
                    pos["child_order_ids"][role] = ""
                    cleared_for_rebracket.add(ticker)
    if cleared_for_rebracket:
        LOG.info(
            "reconcile cleared expired-child IDs for re-bracket: %s",
            sorted(cleared_for_rebracket),
        )
        summary["rebracket_pending"] = sorted(cleared_for_rebracket)

    # Pending signal-fade exits.
    pending = dict(state.get("pending_signal_fade_exits") or {})
    for ticker, pend in pending.items():
        oid = pend.get("exit_order_id")
        broker_view = all_orders_by_id.get(oid, {})
        native = (broker_view.get("native_status") or broker_view.get("status") or "").lower()
        if oid in open_order_ids:
            continue
        if native == "filled" or native == "FILLED".lower():
            pos = open_positions.get(ticker)
            if pos is not None:
                exit_price = float(broker_view.get("filled_avg_price") or 0.0)
                close_position(
                    ticker, state, {},  # cfg unused for closure
                    state_path=state_path, summary_path=summary_path,
                    exit_price=exit_price, reason="signal_fade",
                )
            summary["pending_signal_fade_resolved"].append(f"{ticker}:filled")
        else:
            state.get("pending_signal_fade_exits", {}).pop(ticker, None)
            summary["pending_signal_fade_resolved"].append(f"{ticker}:cleared")

    save_state(state, state_path)
    LOG.info("reconcile complete: %s", summary)
    return summary


# ---------------------------------------------------------------- L2 / L3 kill


def execute_kill_l2(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """L2: cancel + market-out every position not already exiting.
    Returns the list of tickers exited this call. Idempotent — won't
    re-exit positions already in ``status='exiting'``."""
    state["kill_switch_state"] = "L2"
    save_state(state, state_path)
    out: list[str] = []
    for ticker, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "exiting":
            continue
        if pos.get("status") != "filled":
            # Pending parent — best effort cancel. We CANNOT drop the
            # position from state until every cancel call returns
            # success (or a recognized terminal state via
            # cancel_order's idempotent-success branch). A failure here
            # means the broker order may still be live; dropping state
            # in that case strands a real position with no tracking.
            cancel_failures: list[str] = []
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        cancel_order(oid, http, api_key)
                    except Exception as e:
                        LOG.exception("L2 cancel %s child %s failed: %s",
                                      ticker, role, e)
                        cancel_failures.append(f"child:{role}")
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    cancel_order(parent, http, api_key)
                except Exception as e:
                    LOG.exception("L2 cancel parent %s failed: %s", ticker, e)
                    cancel_failures.append("parent")
            if cancel_failures:
                # Keep the position; flag it for operator/reconciliation
                # follow-up. The next reconcile run will compare our
                # tracked order IDs against broker reality and surface
                # the live remnant, instead of it silently floating.
                pos["status"] = "cancel_failed"
                pos["cancel_failures"] = cancel_failures
                pos["cancel_failed_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state, state_path)
                LOG.error(
                    "L2 leaving %s in state with cancel_failed marker "
                    "(failures=%s) — broker may still hold the order",
                    ticker, cancel_failures,
                )
            else:
                state["open_positions"].pop(ticker, None)
                save_state(state, state_path)
            out.append(ticker)
            continue
        trigger_time_stop(
            ticker, pos, cfg, http, api_key,
            state=state, state_path=state_path,
            reason="kill_switch_l2", time_in_force="DAY",
        )
        out.append(ticker)
    return out


def execute_kill_l3(
    state: State,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state_path: Path,
) -> list[str]:
    """L3: cancel + market-out every position best-effort, persist, exit 99.
    Caller is responsible for the actual sys.exit / return 99.

    Item 8 (#4) fix: also cancels pending parent / child orders for
    positions that haven't filled yet. Previously L3 only iterated
    ``status == 'filled'`` and silently left pending orders live —
    asymmetric with L2 and dangerous in a hard-kill where the operator
    expects everything torn down.
    """
    state["kill_switch_state"] = "L3"
    save_state(state, state_path)
    out: list[str] = []
    for ticker, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "filled":
            try:
                trigger_time_stop(
                    ticker, pos, cfg, http, api_key,
                    state=state, state_path=state_path,
                    reason="kill_switch_l3", time_in_force="DAY",
                )
            except Exception:
                LOG.exception("L3 exit failed for %s — best effort", ticker)
        elif pos.get("status") != "exiting":
            # Pending — best-effort cancel of children + parent. Mirrors
            # L2's cancel logic. Unlike L2 we don't keep the position
            # with cancel_failed markers; L3's contract is "best
            # effort, then exit", so we record the attempt and move on.
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        cancel_order(oid, http, api_key)
                    except Exception:
                        LOG.exception(
                            "L3 cancel %s child %s failed (best effort)",
                            ticker, role,
                        )
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    cancel_order(parent, http, api_key)
                except Exception:
                    LOG.exception(
                        "L3 cancel parent %s failed (best effort)", ticker,
                    )
        out.append(ticker)
    save_state(state, state_path)
    return out


# ---------------------------------------------------------------- daily summary


def write_session_summary(
    state: State,
    cfg: dict,
    *,
    summary_path: Path,
    state_path: Path,
    today_iso: str,
) -> dict[str, Any] | None:
    """At session end (15:55 ET), write a session_summary record once
    per day. Counts opened, closed, total realized pnl, exits-by-reason
    from today's jsonl. ``summary_written_for_date`` dedupes."""
    if state.get("summary_written_for_date") == today_iso:
        return None
    if not summary_path.exists():
        # Even with no closures, write the summary so the operator can
        # see "session opened, no trades" days unambiguously.
        record = {
            "record_type": "session_summary",
            "session_date": today_iso,
            "count_opened": 0,
            "count_closed": 0,
            "total_realized_pnl": 0.0,
            "by_reason": {},
        }
        append_closure_record(summary_path, record)
        state["summary_written_for_date"] = today_iso
        save_state(state, state_path)
        return record

    by_reason: dict[str, int] = {}
    total_pnl = 0.0
    count_closed = 0
    # Item 8 (#8): count entries that opened TODAY by walking the
    # ``opened`` records process_fill_events_for_closures wrote when
    # parents transitioned to "filled". This counts intraday round-
    # trips (which the old len(open_positions) missed) and excludes
    # carryover positions (which the old count over-counted).
    count_opened = 0
    with open(summary_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rt = rec.get("record_type")
            if rt == "opened":
                ts = rec.get("entry_timestamp") or ""
                if today_iso in ts:
                    count_opened += 1
                continue
            if rt != "closure":
                continue
            ts = rec.get("exit_timestamp") or rec.get("entry_timestamp") or ""
            if today_iso not in ts:
                continue
            count_closed += 1
            total_pnl += float(rec.get("realized_pnl") or 0.0)
            r = rec.get("reason") or "unknown"
            by_reason[r] = by_reason.get(r, 0) + 1

    record = {
        "record_type": "session_summary",
        "session_date": today_iso,
        "count_opened": count_opened,
        "count_closed": count_closed,
        "total_realized_pnl": total_pnl,
        "by_reason": by_reason,
    }
    append_closure_record(summary_path, record)
    state["summary_written_for_date"] = today_iso
    save_state(state, state_path)
    LOG.info("session summary: opened=%d closed=%d pnl=%.2f reasons=%s",
             count_opened, count_closed, total_pnl, by_reason)
    return record


# ---------------------------------------------------------------- main loop


def _resolve_path(cfg: dict, key: str) -> Path:
    """Paths in the YAML are relative to the script's directory by
    convention; absolute paths pass through unchanged."""
    raw = cfg["paths"][key]
    p = Path(raw)
    if p.is_absolute():
        return p
    # Anchor relative paths at the script's directory.
    return Path(__file__).resolve().parent / p


def run_session_entry_pass(
    cfg: dict,
    state: State,
    state_path: Path,
    http: httpx.Client,
    api_key: str,
    *,
    today_et: date,
    kill_state: KillLevel,
    dry_run: bool = False,
) -> None:
    """First tick of a new session: equity → load+validate candidates
    → reset → select → submit. Idempotent — caller dedupes by
    ``state['session_date']``.

    Item 5 fix: candidate validation runs BEFORE
    ``reset_for_new_session`` writes today's session_date. If the
    candidates file is missing, stale, or hash-mismatched, we return
    without advancing session_date — the next tick will retry. Under
    the previous order an early-morning prefilter glitch (e.g.,
    Alpaca data not yet available, NFS lag, network hiccup) would
    permanently lock out the day's entry pass.
    """
    try:
        equity = fetch_equity(http, api_key)
    except Exception as e:
        LOG.exception("could not fetch equity: %s", e)
        return

    # Item 9: intraday confirmation gate. When enabled, the entry pass
    # waits until ``window_minutes`` after session start so opening-
    # print noise can settle. We use the same Item-5 mechanism (return
    # without advancing session_date) so the next tick retries.
    if _intraday_confirmation_cfg(cfg).get("enabled"):
        if not _intraday_window_elapsed(
            cfg, datetime.now(timezone.utc), today_et,
        ):
            ic = _intraday_confirmation_cfg(cfg)
            LOG.info(
                "intraday_confirmation: window_minutes=%s not yet elapsed; "
                "deferring entry pass to next tick",
                ic.get("window_minutes"),
            )
            return

    candidates_path = _resolve_path(cfg, "candidates_path")
    handshake = cfg.get("prefilter_handshake", {}) or {}
    try:
        cands = load_candidates(
            candidates_path,
            max_age_trading_days=int(handshake.get("max_age_trading_days", 1)),
            expected_config_hash=handshake.get("expected_config_hash"),
            today_et=today_et,
        )
    except CandidatesError as e:
        LOG.error("candidates load failed (will retry next tick): %s", e)
        return

    # Candidates loaded cleanly — now safe to mark today's session
    # baseline. From here on the session_date is committed.
    reset_for_new_session(state, today_et.isoformat(), equity)
    save_state(state, state_path)

    LOG.info("Loaded %d candidates for %s (equity=%.2f)",
             len(cands), today_et, equity)

    entries = select_entries(
        cands, state,
        equity=equity,
        latest_prices={},
        cfg=cfg,
        kill_state=kill_state,
    )
    LOG.info("Selected %d entries: %s", len(entries),
             [e.ticker for e in entries])

    # Item 9: live-quote gate per ticker. When disabled this is a
    # pass-through.
    entries = filter_by_intraday_confirmation(entries, cfg, http, api_key)
    LOG.info("After intraday confirmation: %d entries", len(entries))

    if dry_run:
        LOG.info("dry-run: not submitting entry orders")
        return

    # Compute the running gross at the START of the slate (before
    # any of these submissions add to it) for the entry_decision
    # records. select_entries already gated on this; we re-compute
    # so each entry_decision can carry the snapshot.
    open_positions_at_decision = state.get("open_positions") or {}
    running_gross_at_slate_start = current_gross_exposure(
        open_positions_at_decision, latest_prices={},
    )

    sizing_cfg = cfg.get("sizing") or {}
    risk_cfg = cfg.get("risk") or {}
    per_trade_pct = float(sizing_cfg.get("per_trade_pct") or 0.0)
    max_per_trade_dollars = risk_cfg.get("max_per_trade_dollars")
    max_pos_adv = risk_cfg.get("max_position_as_adv_frac")

    for slot_index, entry in enumerate(entries):
        # Reconstruct sizing rationale: which cap was binding?
        # equity_pct_target = equity * per_trade_pct, optionally
        # capped by max_per_trade_dollars and ADV cap. The binding
        # cap is whichever produced the smallest target_dollars.
        adv = (entry.candidate.features or {}).get("avg_dollar_volume")
        adv_cap_dollars = (
            float(adv) * float(max_pos_adv)
            if (adv is not None and max_pos_adv is not None and float(max_pos_adv) > 0)
            else None
        )
        candidates_target_dollars = [equity * per_trade_pct]
        binding_cap_label = "per_trade_pct"
        if max_per_trade_dollars is not None:
            candidates_target_dollars.append(float(max_per_trade_dollars))
            if float(max_per_trade_dollars) < candidates_target_dollars[0]:
                binding_cap_label = "max_per_trade_dollars"
        if adv_cap_dollars is not None and adv_cap_dollars < min(candidates_target_dollars):
            binding_cap_label = "adv_cap"
        target_dollars = min(candidates_target_dollars + (
            [adv_cap_dollars] if adv_cap_dollars is not None else []
        ))

        # The link_id pattern matches the one submit_*_market_buy
        # uses (ticker + unix seconds), but we generate it here so
        # the entry_decision record can be filed under the same path.
        link_id_for_log = f"BOWAKA-{entry.ticker}-{int(time.time())}"
        try:
            emit_entry_decision(
                cfg, link_id=link_id_for_log, entry=entry, state=state,
                slot_index=slot_index, slate_size=len(entries),
                running_gross_at_entry=running_gross_at_slate_start,
                binding_cap=binding_cap_label,
                target_dollars=target_dollars,
                adv_cap_dollars=adv_cap_dollars,
                # Item 9 gate ran upstream; if entry survived the
                # filter we know it passed (or wasn't applied).
                intraday_confirmation_passed=(
                    True if (cfg.get("entry") or {}).get(
                        "intraday_confirmation", {}
                    ).get("enabled") else None
                ),
            )
        except Exception as e:
            LOG.warning("emit_entry_decision failed for %s: %s", entry.ticker, e)
        # Carry the same link_id forward so submit_* uses it for the
        # parent_submitted record (and pos["link_id"]).
        try:
            submit_entry(
                entry, cfg, http, api_key,
                state=state, state_path=state_path,
                link_id_override=link_id_for_log,
            )
        except httpx.HTTPError as e:
            LOG.exception("entry submit network error for %s: %s",
                          entry.ticker, e)


def run_loop(
    cfg: dict,
    *,
    once: bool = False,
    dry_run: bool = False,
    now_provider=lambda: datetime.now(timezone.utc),
    http_client: httpx.Client | None = None,
    api_key: str | None = None,
) -> int:
    """Main loop. Returns the exit code.

    ``once`` returns after one tick (used by tests). ``now_provider`` is
    pluggable so tests can advance fake time without sleeping.
    ``http_client`` and ``api_key`` are injected by tests; production
    builds them from env vars and YAML.
    """
    state_path = _resolve_path(cfg, "state_path")
    switch_dir = _resolve_path(cfg, "kill_switch_dir")
    interval = float(cfg["session"].get("loop_interval_seconds", 5))

    state = load_state(state_path)
    LOG.info("Loaded state: %d open positions, kill=%s",
             len(state.get("open_positions", {})),
             state.get("kill_switch_state"))

    # HTTP client: tests inject; production builds from env.
    own_http = False
    if http_client is None:
        broker_cfg = cfg.get("broker", {}) or {}
        env_var = broker_cfg.get("base_url_env", "HOST_SERVER")
        base_url = os.environ.get(
            env_var, broker_cfg.get("base_url_default", "http://127.0.0.1:5000")
        )
        timeout = float(broker_cfg.get("timeout_seconds", 15))
        http_client = make_http_client(base_url, timeout=timeout)
        own_http = True
    if api_key is None:
        api_key = os.environ.get("OPENALGO_API_KEY", "")

    summary_path = _resolve_path(cfg, "daily_summary_path")

    # Phase 4: startup reconciliation (no-op when state is empty).
    try:
        reconcile_at_startup(
            state, http_client, api_key,
            state_path=state_path, summary_path=summary_path,
        )
    except Exception as e:
        LOG.exception("startup reconciliation failed (continuing): %s", e)

    try:
        while not _shutdown_requested:
            now = now_provider()
            kill = check_kill_switches(switch_dir)

            if kill is KillLevel.L3_HARD:
                LOG.error("L3 (hard kill) detected — best-effort exit + code 99")
                try:
                    execute_kill_l3(state, cfg, http_client, api_key,
                                    state_path=state_path)
                except Exception as e:
                    LOG.exception("L3 execution failed: %s", e)
                save_state(state, state_path)
                return 99

            if kill is KillLevel.L2_SOFT:
                if state.get("kill_switch_state") != "L2":
                    LOG.warning("L2 (soft kill) detected — market-out all positions")
                try:
                    execute_kill_l2(state, cfg, http_client, api_key,
                                    state_path=state_path)
                except Exception as e:
                    LOG.exception("L2 execution failed: %s", e)
                # L2 idle: continue ticking, no entries, but allow L3 escalation.

            if kill is KillLevel.L1_NEW:
                if state.get("kill_switch_state") != "L1":
                    state["kill_switch_state"] = "L1"
                    save_state(state, state_path)
                LOG.warning("L1 (new entries blocked) detected")

            in_session = is_in_session(
                now,
                start=cfg["session"]["start"],
                end=cfg["session"]["end"],
            )
            if not in_session:
                LOG.debug("outside session window")
            else:
                today_et = _to_eastern(now).date()
                today_iso = today_et.isoformat()
                if state.get("session_date") != today_iso:
                    LOG.info("first session tick for %s — entry pass",
                             today_iso)
                    run_session_entry_pass(
                        cfg, state, state_path, http_client, api_key,
                        today_et=today_et,
                        kill_state=kill,
                        dry_run=dry_run,
                    )
                else:
                    # Subsequent ticks within the same session.
                    try:
                        events = poll_fills(state, http_client, api_key,
                                             state_path=state_path, cfg=cfg)
                    except httpx.HTTPError as e:
                        LOG.exception("poll_fills network error: %s", e)
                        events = []
                    if events:
                        process_fill_events_for_closures(
                            events, state, cfg,
                            state_path=state_path,
                            summary_path=summary_path,
                        )
                    # Item 4 (actual_fill mode): once parents fill we
                    # need to attach the OCO bracket using the real
                    # fill price. Idempotent — only fires for filled
                    # positions still missing child IDs.
                    try:
                        attached = submit_pending_oco_children(
                            state, cfg, http_client, api_key,
                            state_path=state_path,
                        )
                        if attached:
                            LOG.info("OCO brackets attached post-fill: %s", attached)
                    except Exception as e:
                        LOG.exception("submit_pending_oco_children failed: %s", e)
                    # Per-trade rich logging: 1-minute intraday tick
                    # snapshot per filled position. Idempotent — each
                    # position has its own ``last_tick_logged_at`` so
                    # this is a no-op until 60s have elapsed since
                    # the previous snapshot for that ticker.
                    try:
                        tick_interval = int(
                            (cfg.get("logging") or {}).get(
                                "intraday_tick_interval_seconds", 60,
                            )
                        )
                        run_intraday_tick_logging(
                            cfg, state, http_client, api_key,
                            state_path=state_path, now_utc=now,
                            interval_seconds=tick_interval,
                        )
                    except Exception as e:
                        LOG.exception("intraday tick logging error: %s", e)
                    # Phase 4: daily P&L tracking.
                    try:
                        eq = fetch_equity(http_client, api_key)
                        update_daily_pnl(state, eq, cfg, state_path=state_path)
                    except Exception as e:
                        LOG.warning("equity check failed (continuing): %s", e)
                    # Time-stop and signal-fade are SUPERSEDED under L2.
                    today_et = _to_eastern(now).date()
                    if kill not in (KillLevel.L2_SOFT,):
                        try:
                            run_time_stop_pass(
                                cfg, state, http_client, api_key,
                                today_et=today_et, state_path=state_path,
                            )
                        except Exception as e:
                            LOG.exception("time-stop pass error: %s", e)
                    # Session-end summary (15:55 ET tick).
                    et_dt = _to_eastern(now)
                    end_h, end_m = (int(x) for x in cfg["session"]["end"].split(":"))
                    if et_dt.hour == end_h and et_dt.minute == end_m:
                        try:
                            write_session_summary(
                                state, cfg,
                                summary_path=summary_path,
                                state_path=state_path,
                                today_iso=today_et.isoformat(),
                            )
                        except Exception as e:
                            LOG.exception("session summary write failed: %s", e)

            # Signal-fade EOD subroutine — runs at the configured eval
            # minute on a NYSE trading day, even if outside regular
            # session window (16:05 ET is post-close). Superseded under L2.
            sf_eval = cfg["session"].get("signal_fade_eval_time", "16:05")
            if kill not in (KillLevel.L2_SOFT,) and is_signal_fade_window(now, sf_eval):
                today_et = _to_eastern(now).date()
                # Analytic logging: write today's mark for every
                # filled position BEFORE the signal-fade exit pass.
                # Doing this first means a position that signal-fades
                # this tick still gets a closing mark recorded with
                # today's high/low/close + fresh feature values, which
                # the analyst needs to study why the gates failed.
                try:
                    write_daily_marks(
                        cfg, state, http_client, api_key,
                        today_et=today_et,
                        summary_path=summary_path,
                        state_path=state_path,
                        now_utc=now,
                    )
                except Exception as e:
                    LOG.exception("daily_mark pass error: %s", e)
                try:
                    run_signal_fade_pass(
                        cfg, state, http_client, api_key,
                        today_et=today_et, state_path=state_path,
                        now_utc=now,
                    )
                except Exception as e:
                    LOG.exception("signal-fade pass error: %s", e)

            if once:
                break

            # Sleep in small chunks so the shutdown flag is honored quickly.
            slept = 0.0
            while slept < interval and not _shutdown_requested:
                chunk = min(0.5, interval - slept)
                time.sleep(chunk)
                slept += chunk
    finally:
        if own_http:
            http_client.close()

    # Clean shutdown.
    save_state(state, state_path)
    LOG.info("shutdown complete")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka /python strategy")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip live order placement (used by later-phase paths)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one main-loop tick then exit (tests)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg)
    cfg_hash = config_hash(cfg)
    LOG.info("Starting bowaka strategy (config_hash=%s)", cfg_hash)

    # Item 8 (handshake): cross-check signal_gates + indicators against
    # the prefilter yaml so the EOD signal-fade exits never use
    # thresholds the prefilter never applied. Failure raises
    # HandshakeMismatch — operator must reconcile and restart.
    try:
        verify_prefilter_handshake(cfg)
    except HandshakeMismatch as e:
        LOG.error("prefilter handshake failed: %s", e)
        return 5

    if not os.environ.get("OPENALGO_API_KEY"):
        LOG.error("OPENALGO_API_KEY must be set in env")
        return 2
    host = os.environ.get("HOST_SERVER", "http://127.0.0.1:5000")
    LOG.info("HOST_SERVER=%s", host)

    strat_exch = os.environ.get("OPENALGO_STRATEGY_EXCHANGE")
    if strat_exch != "CRYPTO":
        LOG.warning(
            "OPENALGO_STRATEGY_EXCHANGE=%r (expected 'CRYPTO' for the "
            "/python host workaround). Continuing.",
            strat_exch,
        )

    install_signal_handlers()
    return run_loop(cfg, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
