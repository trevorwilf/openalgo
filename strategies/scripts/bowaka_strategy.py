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
from datetime import date, datetime, timezone
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
) -> int:
    """floor(min(equity*pct, abs_cap) / close). Whole shares only —
    bracket orders reject fractional at Alpaca. Returns 0 when the
    target dollars don't cover one share (caller skips)."""
    target = equity * per_trade_pct
    if max_per_trade_dollars is not None:
        target = min(target, max_per_trade_dollars)
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
    candidate: Candidate


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
        qty = compute_qty(
            equity=equity,
            close_price=cand.close,
            per_trade_pct=per_trade_pct,
            max_per_trade_dollars=max_per_trade_abs,
        )
        if qty <= 0:
            continue
        notional = qty * cand.close
        if gross_cap > 0 and (running_gross + notional) > gross_cap:
            continue
        running_gross += notional
        selected.append(Entry(
            ticker=cand.ticker,
            qty=qty,
            close_price=cand.close,
            candidate=cand,
        ))
    return selected


# ---------------------------------------------------------------- OTOCO


def submit_otoco(
    entry: Entry,
    cfg: dict,
    http: httpx.Client,
    api_key: str,
    *,
    state: State,
    state_path: Path,
) -> dict[str, Any]:
    """POST /api/v2/orders/combo with an OTOCO bracket. Records state
    on success. Marks halt_skip_today on bracket / instrument-mapping
    422s. Surfaces 503 translator/lane errors loudly.

    Returns the parsed JSON response, or a dict with ``error`` when the
    server returned a structured error.
    """
    target = round(entry.close_price * (1.0 + float(cfg["exits"]["target_pct"])), 2)
    stop = round(entry.close_price * (1.0 - float(cfg["exits"]["stop_pct"])), 2)
    venue_code = cfg["sizing"]["default_venue_code"]
    link_id = f"BOWAKA-{entry.ticker}-{int(time.time())}"

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
            "target_price": target,
            "stop_price": stop,
        }
        save_state(state, state_path)
        LOG.info("OTOCO submitted: %s qty=%d parent=%s",
                 entry.ticker, entry.qty, parent_id)
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
                    dirty = True
                    events.append(ev)
            elif status in _DEAD or canonical in {s.upper() for s in _DEAD}:
                if filled_qty > 0:
                    # Partial fill before cancel/reject — keep the
                    # filled portion and log the remainder.
                    pos["status"] = "filled"
                    pos["qty"] = filled_qty
                    pos["entry_price"] = filled_avg_f or pos.get("entry_price")
                    LOG.warning(
                        "parent %s ended in %s with partial fill %d shares",
                        ticker, canonical, filled_qty,
                    )
                else:
                    open_positions.pop(ticker, None)
                    LOG.info("parent %s ended in %s — position dropped", ticker, canonical)
                dirty = True
                events.append(ev)

        elif role in ("target", "stop") and pos is not None:
            if status in _FILLED:
                pos.setdefault("filled_children", {})[role] = {
                    "filled_qty": filled_qty,
                    "filled_avg_price": filled_avg_f,
                }
                dirty = True
                events.append(ev)

        elif role == "exit" and pos is not None:
            if status in _FILLED:
                pos["exit_fill_price"] = filled_avg_f
                pos["exit_filled_qty"] = filled_qty
                # Phase 3 will close the position on this signal.
                dirty = True
                events.append(ev)

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
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    exit_id = data.get("order_id") or data.get("id") or ""
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


# ---------------------------------------------------------------- closures


def append_closure_record(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON-Lines record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()


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
    """Compute realized PnL, append jsonl, drop from state."""
    pos = (state.get("open_positions") or {}).get(ticker)
    if pos is None:
        return {}
    entry_price = float(pos.get("entry_price") or 0.0)
    qty = int(pos.get("qty") or 0)
    realized = (exit_price - entry_price) * qty
    record = {
        "record_type": "closure",
        "ticker": ticker,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_timestamp": pos.get("entry_timestamp"),
        "exit_timestamp": datetime.now(timezone.utc).isoformat(),
        "realized_pnl": realized,
        "reason": reason,
        "entry_features": pos.get("entry_features", {}),
    }
    append_closure_record(summary_path, record)
    state["open_positions"].pop(ticker, None)
    state.get("pending_signal_fade_exits", {}).pop(ticker, None)
    save_state(state, state_path)
    LOG.info("closed %s: %s pnl=%.2f", ticker, reason, realized)
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

    - target child filled → ``target_hit``
    - stop child filled   → ``stop_hit``
    - exit_order_id filled → use the recorded exit reason (time_stop / signal_fade)
    """
    out: list[dict[str, Any]] = []
    open_positions = state.get("open_positions") or {}
    for ev in events:
        pos = open_positions.get(ev.ticker)
        if pos is None:
            continue
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
    main loop. Returns a summary dict for logging."""
    summary = {
        "qty_corrected": [], "closed_externally": [], "untracked": [],
        "child_status_corrected": [], "pending_signal_fade_resolved": [],
    }
    open_positions = state.get("open_positions") or {}
    if not open_positions and not state.get("pending_signal_fade_exits"):
        LOG.info("reconciliation: empty state, fresh start")
        return summary

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
    for ticker, pos in open_positions.items():
        for role, oid in (pos.get("child_order_ids") or {}).items():
            if oid and oid not in open_order_ids:
                broker_view = all_orders_by_id.get(oid, {})
                native = (broker_view.get("native_status")
                          or broker_view.get("status") or "")
                if native:
                    pos.setdefault("child_status_at_recon", {})[role] = native
                    summary["child_status_corrected"].append(f"{ticker}:{role}={native}")

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
    Caller is responsible for the actual sys.exit / return 99."""
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
            "count_opened": len(state.get("open_positions") or {}),
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
    with open(summary_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("record_type") != "closure":
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
        "count_opened": len(state.get("open_positions") or {}),
        "count_closed": count_closed,
        "total_realized_pnl": total_pnl,
        "by_reason": by_reason,
    }
    append_closure_record(summary_path, record)
    state["summary_written_for_date"] = today_iso
    save_state(state, state_path)
    LOG.info("session summary: closed=%d pnl=%.2f reasons=%s",
             count_closed, total_pnl, by_reason)
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
    """First tick of a new session: equity → reset → load candidates →
    select → submit OTOCO. Idempotent — caller dedupes by
    ``state['session_date']``."""
    try:
        equity = fetch_equity(http, api_key)
    except Exception as e:
        LOG.exception("could not fetch equity: %s", e)
        return

    reset_for_new_session(state, today_et.isoformat(), equity)
    save_state(state, state_path)

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
        LOG.error("candidates load failed: %s", e)
        return

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

    if dry_run:
        LOG.info("dry-run: not submitting OTOCO orders")
        return

    for entry in entries:
        try:
            submit_otoco(entry, cfg, http, api_key,
                         state=state, state_path=state_path)
        except httpx.HTTPError as e:
            LOG.exception("OTOCO submit network error for %s: %s",
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
                                             state_path=state_path)
                    except httpx.HTTPError as e:
                        LOG.exception("poll_fills network error: %s", e)
                        events = []
                    if events:
                        process_fill_events_for_closures(
                            events, state, cfg,
                            state_path=state_path,
                            summary_path=summary_path,
                        )
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
