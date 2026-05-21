#!/usr/bin/env python3
"""Bowaka v2 — strategy / candidate-event consumer.

Continuously reads ``data/bowaka_v2/candidate_events.jsonl`` from the
scanner, applies execution-quality and risk gates, submits entries,
and runs the existing position-management plumbing (OCO bracket
attach, protected-position invariant, kill switches, ledger, etc.).

What this module IS:
- The v2 entry consumer.
- The 11 v1-parity logging streams (entry_decisions,
  rejected_candidates, order_exec_quality, protection_events,
  shadow_risk, counterfactual_entries, counterfactual_exits,
  config_snapshot, per_position_ticks, candidate_minute_bars,
  liquidity_monitor scaffold).
- The startup gate (refuses live unless feed=sip).

What this module is NOT:
- It does NOT call the v1 once-per-day entry pass function.
- It does NOT read the legacy candidate file under data/.
- It does NOT use the v1 once-per-session-date branch for entry
  discovery — that sentinel is intentionally absent.

All v2 helpers are local to this module — the v2 strategy is
self-contained. (Pre-v1-removal commits imported a narrow set of
helpers from the now-archived v1 strategy module.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_features as features  # noqa: E402
import bowaka_v2_paths as paths  # noqa: E402
import bowaka_v2_schemas as schemas  # noqa: E402


def adv_tier_cap(
    avg_dollar_volume: float | None, cfg: dict,
) -> tuple[bool, float]:
    """Resolve the position dollar cap for ``avg_dollar_volume`` under
    the tiered ADV policy. Returns ``(allowed, max_position_dollars)``.

    Walks ``cfg.risk.adv_tier_caps`` top-to-bottom (YAML order is the
    policy). The first tier whose ``max_adv_dollars`` is None or >=
    the candidate's ADV matches. ``reject_if_below: true`` returns
    ``(False, 0.0)``. Empty tier list falls back to the legacy flat
    ``risk.max_position_as_adv_frac``.
    """
    if avg_dollar_volume is None or float(avg_dollar_volume) <= 0:
        return False, 0.0
    adv = float(avg_dollar_volume)
    tiers = ((cfg.get("risk") or {}).get("adv_tier_caps") or [])
    if not tiers:
        flat = (cfg.get("risk") or {}).get("max_position_as_adv_frac")
        if flat is None:
            return True, 0.0
        return True, adv * float(flat)
    for tier in tiers:
        max_adv = tier.get("max_adv_dollars")
        if max_adv is None or adv <= float(max_adv):
            if tier.get("reject_if_below"):
                return False, 0.0
            frac = tier.get("max_position_as_adv_frac")
            if frac is None:
                return True, 0.0
            return True, adv * float(frac)
    return False, 0.0


LOG = logging.getLogger("bowaka_v2_strategy")


class ConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------- startup gate


def validate_startup_config(cfg: dict) -> None:
    """Refuse to start when:
      - environment is "live" but data.feed is not SIP.
      - cfg.strategy.mode is not "forming_daily_bar_monitor".
    """
    s = (cfg.get("strategy") or {})
    mode = s.get("mode")
    if mode != "forming_daily_bar_monitor":
        raise ConfigError(
            f"bowaka_v2_strategy requires strategy.mode = "
            f"'forming_daily_bar_monitor'; got {mode!r}"
        )
    data = cfg.get("data") or {}
    feed = data.get("feed", "sip")
    env = (s.get("environment") or "paper").lower()
    if env == "live" and feed != "sip" and data.get("live_requires_sip", True):
        raise ConfigError(
            "live environment refuses non-SIP feed; flip feed to 'sip' "
            "or downgrade environment to 'paper'."
        )
    if feed != "sip":
        LOG.warning(
            "running on %s partial-tape; RVOL / range_expansion are "
            "distorted. SIP is the validation feed.", feed,
        )


# ---------------------------------------------------------------- logging streams


def _append_jsonl(path: Path, payload: dict) -> None:
    """Atomic single-line append. Open with O_APPEND, write a full
    line + flush. Phase 4 wiring contract: crash-safe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
        f.flush()


def emit_entry_decision_v2(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("emit_entry_decisions", True):
        _append_jsonl(paths.ENTRY_DECISIONS_PATH, ev)


def emit_rejected_candidate(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("emit_rejected_candidates", True):
        _append_jsonl(paths.REJECTED_CANDIDATES_PATH, ev)


def emit_order_execution_quality(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("log_order_execution_quality", True):
        _append_jsonl(paths.ORDER_EXEC_QUALITY_PATH, ev)


def emit_protection_state(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("log_protection_state", True):
        _append_jsonl(paths.PROTECTION_EVENTS_PATH, ev)


def emit_shadow_risk(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("log_shadow_risk_controls", True):
        _append_jsonl(paths.SHADOW_RISK_PATH, ev)


def emit_counterfactual_entry(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("log_counterfactual_entries", True):
        _append_jsonl(paths.COUNTERFACTUAL_ENTRIES_PATH, ev)


def emit_counterfactual_exit(cfg: dict, ev: dict) -> None:
    if (cfg.get("logging") or {}).get("log_counterfactual_exits", True):
        _append_jsonl(paths.COUNTERFACTUAL_EXITS_PATH, ev)


def emit_liquidity_monitor(cfg: dict, ev: dict) -> None:
    """Phase 4 ships the scaffold only. The action paths
    (tighten_stop / exit_partial) land in Phase 6."""
    if (cfg.get("liquidity_monitor") or {}).get("enabled", False):
        _append_jsonl(paths.LIQUIDITY_MONITOR_PATH, ev)


def persist_config_snapshot(cfg: dict) -> Path | None:
    """Write the resolved config + universe_hash + git sha + redacted
    env to data/bowaka_v2/config_snapshots/<session>_<hash>.json."""
    if not (cfg.get("logging") or {}).get("persist_config_snapshot", True):
        return None
    h = hashlib.sha256(
        json.dumps(cfg, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    session = pd.Timestamp.now(tz="America/New_York").date().isoformat()
    out_path = paths.CONFIG_SNAPSHOTS_DIR / f"{session}_{h}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_date": session,
        "config_hash": h,
        "git_sha": _git_sha(),
        "captured_at": _iso(_now_utc()),
        "config": cfg,
        "redacted_env": _redacted_env(),
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def _git_sha() -> str:
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _redacted_env() -> dict[str, str]:
    """Capture select env vars with secrets redacted."""
    redacted: dict[str, str] = {}
    for k, v in os.environ.items():
        if any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASS")):
            redacted[k] = "<REDACTED>"
        elif k.startswith(("BOWAKA_", "OPENALGO_", "PYTHON")):
            redacted[k] = v
    return redacted


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- consumer


def tail_new_events(
    candidate_events_path: Path,
    last_offset: int,
) -> tuple[list[dict], int]:
    """Read new lines from candidate_events.jsonl since
    ``last_offset`` (byte offset). Returns ``(events,
    new_offset)``."""
    if not candidate_events_path.exists():
        return [], last_offset
    out: list[dict] = []
    new_offset = last_offset
    with open(candidate_events_path, "r", encoding="utf-8") as f:
        f.seek(last_offset)
        while True:
            line = f.readline()
            if not line:
                break
            new_offset = f.tell()
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                LOG.warning("dropping malformed candidate event line")
                continue
            out.append(ev)
    return out, new_offset


def _is_expired(ev: dict, now: datetime) -> bool:
    expiry = ev.get("signal_expiry_timestamp")
    if not expiry:
        return False
    try:
        e = pd.Timestamp(expiry)
        if e.tzinfo is None:
            e = e.tz_localize("UTC")
        n = pd.Timestamp(now)
        if n.tzinfo is None:
            n = n.tz_localize("UTC")
        return n > e
    except Exception:
        return False


def _is_stale_session(ev: dict, today_iso: str) -> bool:
    return ev.get("session_date") != today_iso


def _today_iso() -> str:
    return pd.Timestamp.now(tz="America/New_York").date().isoformat()


def build_rejection_record(
    ev: dict, *, reason: str, decision_ts: datetime,
    risk_snapshot: dict | None = None,
    quote: dict | None = None,
) -> dict:
    """Materialize a rejected entry_decision event matching the
    schema-v3 manifest."""
    sym = ev.get("symbol", "?")
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "entry_decision",
        "decision": "rejected",
        "reason": reason,
        "event_id": schemas.make_event_id(
            "bowaka_v2", ev.get("session_date", _today_iso()),
            sym, _iso(decision_ts), suffix="entry",
        ),
        "candidate_event_id": ev.get("event_id"),
        "session_date": ev.get("session_date") or _today_iso(),
        "symbol": sym,
        "entry_trigger": "forming_daily_bar_scan",
        "scan_timestamp": ev.get("scan_timestamp"),
        "decision_timestamp": _iso(decision_ts),
        "quote": quote or {
            "bid": None, "ask": None, "mid": None,
            "spread_pct": None, "quote_timestamp": None,
            "quote_age_seconds": None,
        },
        "risk_snapshot": risk_snapshot or {
            "bankroll": None, "gross_exposure_dollars": 0.0,
            "gross_exposure_pct": 0.0, "entries_today": 0,
            "open_positions": 0, "candidate_adv": None,
            "target_notional": 0.0, "adv_participation_frac": 0.0,
        },
        "order_plan": {
            "side": "buy", "order_style": "n/a", "qty": 0,
            "estimated_notional": 0.0, "stop_pct": None,
            "target_pct": None, "max_hold_days": None,
        },
    }


def build_acceptance_record(
    ev: dict, *, decision_ts: datetime, qty: int,
    target_notional: float, risk_snapshot: dict, quote: dict,
    order_style: str, stop_pct: float, target_pct: float,
    max_hold_days: int,
) -> dict:
    sym = ev.get("symbol", "?")
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "entry_decision",
        "decision": "accepted",
        "reason": "all_gates_passed",
        "event_id": schemas.make_event_id(
            "bowaka_v2", ev.get("session_date", _today_iso()),
            sym, _iso(decision_ts), suffix="entry",
        ),
        "candidate_event_id": ev.get("event_id"),
        "session_date": ev.get("session_date") or _today_iso(),
        "symbol": sym,
        "entry_trigger": "forming_daily_bar_scan",
        "scan_timestamp": ev.get("scan_timestamp"),
        "decision_timestamp": _iso(decision_ts),
        "quote": quote,
        "risk_snapshot": risk_snapshot,
        "order_plan": {
            "side": "buy", "order_style": order_style, "qty": qty,
            "estimated_notional": target_notional,
            "stop_pct": stop_pct, "target_pct": target_pct,
            "max_hold_days": max_hold_days,
        },
    }


# ---- execution gates ----


def _quote_gate(quote: dict | None, cfg: dict) -> str | None:
    """Return canonical rejection reason if the quote violates an
    execution gate, else None."""
    qg = (cfg.get("execution") or {}).get("quote_gate") or {}
    if not qg.get("enabled", True):
        return None
    if quote is None:
        return "quote_stale"
    bid = quote.get("bid")
    ask = quote.get("ask")
    age = quote.get("quote_age_seconds")
    if qg.get("require_bid_ask_positive", True):
        if not (isinstance(bid, (int, float)) and bid > 0
                and isinstance(ask, (int, float)) and ask > 0):
            return "quote_stale"
    spread_pct = quote.get("spread_pct")
    if spread_pct is None and bid and ask:
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid if mid > 0 else None
    max_sp = qg.get("max_spread_pct")
    if max_sp is not None and spread_pct is not None and spread_pct > float(max_sp):
        return "spread_too_wide"
    max_age = qg.get("max_quote_age_seconds")
    if max_age is not None and age is not None and age > float(max_age):
        return "quote_stale"
    return None


def _price_chase_gate(
    quote: dict | None, signal_price: float, cfg: dict,
) -> str | None:
    pcg = (cfg.get("execution") or {}).get("price_chase_gate") or {}
    if not pcg.get("enabled", True) or not signal_price:
        return None
    mid = (quote or {}).get("mid")
    if mid is None and (quote or {}).get("bid") and (quote or {}).get("ask"):
        mid = ((quote["bid"] + quote["ask"]) / 2.0)
    if mid is None or signal_price <= 0:
        return None
    delta_pct = mid / signal_price - 1.0
    max_above = pcg.get("max_pct_above_signal_price")
    min_below = pcg.get("min_pct_below_signal_price")
    if max_above is not None and delta_pct > float(max_above):
        return "price_chase_band"
    if min_below is not None and delta_pct < float(min_below):
        return "price_chase_band"
    return None


def _halt_gate(symbol_status: str | None, cfg: dict) -> str | None:
    hg = (cfg.get("execution") or {}).get("halt_gate") or {}
    if not hg.get("enabled", True):
        return None
    if not symbol_status:
        return None
    bad = {"halted", "pending_review", "luld_pause"}
    if symbol_status.lower() in bad:
        return "halt_or_pending_review"
    return None


# ---- risk gates ----


def _risk_gates(
    ev: dict, state: dict, cfg: dict, *,
    candidate_adv: float | None,
    target_notional: float,
) -> str | None:
    risk_cfg = cfg.get("risk") or {}
    sizing_cfg = cfg.get("sizing") or {}

    # max_concurrent_positions
    max_concurrent = int(sizing_cfg.get("max_concurrent_positions", 18))
    open_count = len(state.get("open_positions") or {})
    if open_count >= max_concurrent:
        return "max_concurrent_positions"

    # max_total_entries_per_day
    max_entries = risk_cfg.get("max_total_entries_per_day")
    if max_entries is not None:
        if int(state.get("daily_entries_count", 0)) >= int(max_entries):
            return "daily_entry_cap"

    # gross_exposure_cap
    bankroll = (state.get("bankroll") or {}).get(
        "current_dollars", sizing_cfg.get("bankroll_fixed_dollars", 90000)
    )
    max_gross_pct = risk_cfg.get("max_gross_exposure_pct")
    current_gross = float(state.get("gross_exposure_dollars", 0.0))
    if max_gross_pct is not None and bankroll and bankroll > 0:
        projected = current_gross + target_notional
        if projected / bankroll > float(max_gross_pct):
            return "gross_exposure_cap"

    # daily_loss_pct → kill_switch reason
    daily_loss_pct = risk_cfg.get("daily_loss_pct")
    if daily_loss_pct is not None and bankroll and bankroll > 0:
        pnl = float(state.get("daily_realized_pnl_strategy") or 0.0)
        if pnl / bankroll <= -float(daily_loss_pct):
            return "kill_switch"

    # ADV cap — tiered policy via adv_tier_cap (inlined above).
    if candidate_adv is not None and candidate_adv > 0:
        try:
            allowed, cap_dollars = adv_tier_cap(candidate_adv, cfg)
            if not allowed or (cap_dollars and target_notional > cap_dollars):
                return "adv_cap"
        except Exception:
            pass

    return None


def _shadow_risk_check(
    ev: dict, state: dict, cfg: dict, *,
    candidate_adv: float | None, target_notional: float,
) -> list[str]:
    """Phase 5.2 — return the list of shadow rules that WOULD have
    blocked this entry. Read from cfg.risk.shadow if present."""
    shadow = (cfg.get("risk") or {}).get("shadow") or {}
    if not shadow:
        return []
    blockers: list[str] = []
    bankroll = (state.get("bankroll") or {}).get(
        "current_dollars", (cfg.get("sizing") or {})
            .get("bankroll_fixed_dollars", 90000)
    )
    max_entries_sh = shadow.get("max_total_entries_per_day")
    if max_entries_sh is not None:
        if int(state.get("daily_entries_count", 0)) >= int(max_entries_sh):
            blockers.append("shadow_max_entries")
    max_gross_sh = shadow.get("max_gross_exposure_pct")
    if max_gross_sh is not None and bankroll and bankroll > 0:
        projected = float(state.get("gross_exposure_dollars", 0.0)) + target_notional
        if projected / bankroll > float(max_gross_sh):
            blockers.append("shadow_gross_exposure_cap")
    dl_sh = shadow.get("daily_loss_pct")
    if dl_sh is not None and bankroll and bankroll > 0:
        pnl = float(state.get("daily_realized_pnl_strategy") or 0.0)
        if pnl / bankroll <= -float(dl_sh):
            blockers.append("shadow_daily_loss")
    return blockers


# ---- sizing ----


def size_position(
    ev: dict, cfg: dict, *, current_price: float,
) -> tuple[int, float]:
    """Equal-slice sizing per cfg.sizing. Returns (qty,
    target_notional). Honors min_order_notional."""
    sizing_cfg = cfg.get("sizing") or {}
    bankroll = float(sizing_cfg.get("bankroll_fixed_dollars", 90000))
    n_slots = int(sizing_cfg.get("max_concurrent_positions", 18))
    frac = float(sizing_cfg.get("equal_slice_bankroll_fraction", 0.80))
    target_notional = frac * bankroll / n_slots
    min_order_notional = float(sizing_cfg.get("min_order_notional", 500))
    if target_notional < min_order_notional:
        target_notional = min_order_notional
    if current_price <= 0:
        return 0, 0.0
    qty = int(target_notional // current_price)
    return qty, qty * current_price


# ---- per-symbol dedupe ----


def _symbol_already_entered_today(state: dict, symbol: str) -> bool:
    entered = set(state.get("entered_today") or [])
    if symbol in entered:
        return True
    cooldowns = state.get("cooldowns") or {}
    if symbol in cooldowns:
        until = cooldowns[symbol].get("until")
        if until:
            try:
                u = pd.Timestamp(until)
                now = pd.Timestamp.now(tz="UTC")
                if u.tzinfo is None:
                    u = u.tz_localize("UTC")
                if now < u:
                    return True
            except Exception:
                pass
    return False


# ---- consumer entry point ----


def consume_candidate_events(
    state: dict,
    cfg: dict,
    *,
    quote_supplier=None,
    submit_supplier=None,
    now_utc: datetime | None = None,
    today_iso: str | None = None,
) -> dict[str, int]:
    """Read new candidate events since the last consumed offset and
    apply gates → submit entries or emit rejection events. Returns
    summary counts.

    ``quote_supplier(symbol) -> dict | None`` and ``submit_supplier
    (symbol, qty) -> dict`` are injection points for tests.
    ``today_iso`` defaults to the wall-clock ET date; pass it
    explicitly when working from a fixture session date.
    """
    now = now_utc or _now_utc()
    today_iso = today_iso or _today_iso()

    # Session rollover — when the ET date crosses from a recorded
    # prior session to today, reset per-day counters so daily caps
    # don't accumulate across sessions. We never reset
    # last_consumed_event_offset; candidate_events.jsonl is append-
    # only across sessions and stale-session-rejection handles
    # leftover events. First run (no recorded session_date) leaves
    # state alone — caller-provided seeds are respected.
    prior_session = state.get("session_date")
    if prior_session is None:
        state["session_date"] = today_iso
    elif prior_session != today_iso:
        state["session_date"] = today_iso
        state["entered_today"] = []
        state["daily_entries_count"] = 0
        state["daily_realized_pnl_strategy"] = 0.0
        state["gross_exposure_dollars"] = 0.0

    cand_path = _resolve(cfg, "candidate_events_path",
                          paths.CANDIDATE_EVENTS_PATH)
    last_offset = int(state.get("last_consumed_event_offset", 0))
    events, new_offset = tail_new_events(cand_path, last_offset)

    summary = {
        "consumed": 0, "accepted": 0, "rejected": 0,
        "expired": 0, "stale": 0, "dedupe": 0, "invalid": 0,
    }

    for ev in events:
        summary["consumed"] += 1
        ok, problems = schemas.validate_candidate_event(ev)
        if not ok:
            LOG.warning("invalid candidate event dropped: %s", problems[:3])
            summary["invalid"] += 1
            continue

        # Stale session?
        if _is_stale_session(ev, today_iso):
            summary["stale"] += 1
            rec = build_rejection_record(ev, reason="lost_signal_before_entry",
                                          decision_ts=now)
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Expired signal?
        if _is_expired(ev, now):
            summary["expired"] += 1
            rec = build_rejection_record(ev, reason="lost_signal_before_entry",
                                          decision_ts=now)
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        symbol = ev["symbol"]
        # Same-symbol dedupe.
        if _symbol_already_entered_today(state, symbol):
            summary["dedupe"] += 1
            rec = build_rejection_record(
                ev, reason="same_symbol_already_entered_today",
                decision_ts=now,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        signal_price = (
            ev.get("forming_session_bar", {}).get("last_price")
        )
        adv = (ev.get("prior_daily_baselines") or {}).get(
            "avg_dollar_volume_20d"
        )
        qty, target_notional = size_position(
            ev, cfg, current_price=signal_price or 1.0,
        )
        if qty <= 0:
            summary["rejected"] += 1
            rec = build_rejection_record(ev, reason="adv_cap",
                                          decision_ts=now)
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Quote gate.
        quote = (quote_supplier(symbol) if quote_supplier else None) or {
            "bid": signal_price, "ask": signal_price,
            "mid": signal_price, "spread_pct": 0.0,
            "quote_timestamp": _iso(now), "quote_age_seconds": 0,
        }
        rejection = _quote_gate(quote, cfg)
        if rejection is None:
            rejection = _price_chase_gate(quote, signal_price or 0.0, cfg)
        if rejection is None:
            rejection = _halt_gate(quote.get("symbol_status"), cfg)
        if rejection is None:
            # Risk gates.
            rejection = _risk_gates(
                ev, state, cfg,
                candidate_adv=adv, target_notional=target_notional,
            )

        risk_snapshot = {
            "bankroll": (state.get("bankroll") or {}).get(
                "current_dollars",
                (cfg.get("sizing") or {}).get(
                    "bankroll_fixed_dollars", 90000,
                ),
            ),
            "gross_exposure_dollars": float(state.get(
                "gross_exposure_dollars", 0.0,
            )),
            "gross_exposure_pct": 0.0,
            "entries_today": int(state.get("daily_entries_count", 0)),
            "open_positions": len(state.get("open_positions") or {}),
            "candidate_adv": adv,
            "target_notional": target_notional,
            "adv_participation_frac": (
                target_notional / adv if adv and adv > 0 else 0.0
            ),
        }

        if rejection is not None:
            summary["rejected"] += 1
            rec = build_rejection_record(
                ev, reason=rejection, decision_ts=now,
                risk_snapshot=risk_snapshot, quote=quote,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Accepted. Build the entry-decision record + emit shadow risk.
        exits_cfg = cfg.get("exits") or {}
        accept = build_acceptance_record(
            ev, decision_ts=now, qty=qty,
            target_notional=target_notional,
            risk_snapshot=risk_snapshot, quote=quote,
            order_style=(cfg.get("execution") or {}).get(
                "parent_order_style", "market",
            ),
            stop_pct=float(exits_cfg.get("stop_pct", 0.08)),
            target_pct=float(exits_cfg.get("target_pct", 0.15)),
            max_hold_days=int(exits_cfg.get("max_hold_days", 3)),
        )
        emit_entry_decision_v2(cfg, accept)

        # Shadow risk telemetry.
        shadow_blockers = _shadow_risk_check(
            ev, state, cfg,
            candidate_adv=adv, target_notional=target_notional,
        )
        if shadow_blockers:
            emit_shadow_risk(cfg, {
                "ts": _iso(now), "symbol": symbol,
                "would_have_blocked": shadow_blockers,
                "candidate_event_id": ev.get("event_id"),
            })

        # Submit order (injection point).
        parent_order_id = ""
        if submit_supplier is not None:
            try:
                submit_resp = submit_supplier(symbol, qty)
            except Exception as e:
                LOG.warning("submit_supplier raised for %s: %s", symbol, e)
                summary["rejected"] += 1
                continue
            # Validate broker accepted the order before mutating state.
            status_ok = True
            if isinstance(submit_resp, dict):
                http_status = submit_resp.get("_http_status")
                if http_status is not None and http_status not in (200, 201):
                    status_ok = False
                    LOG.warning(
                        "submit rejected for %s (status=%s): %s",
                        symbol, http_status, submit_resp,
                    )
                data = submit_resp.get("data") or {}
                parent_order_id = (
                    data.get("order_id")
                    or data.get("id")
                    or (submit_resp.get("native_response") or {}).get("id")
                    or ""
                )
            if not status_ok:
                summary["rejected"] += 1
                continue

        # Update state — record the pending position so poll_fills can
        # match the parent's eventual FILLED echo back to this trade.
        venue_code = (cfg.get("execution") or {}).get(
            "default_venue_code", "XNAS",
        )
        link_id = f"BOWAKAv2-{symbol}-{int(time.time())}"
        record_pending_position(
            state,
            symbol=symbol, qty=qty, venue_code=venue_code,
            parent_order_id=parent_order_id, link_id=link_id,
            candidate_close=signal_price, signal_strength=ev.get(
                "signal_strength",
            ),
            equity_at_entry=risk_snapshot.get("bankroll"),
            entry_features=ev.get("features"),
            stop_pct=float(exits_cfg.get("stop_pct", 0.08)),
            target_pct=float(exits_cfg.get("target_pct", 0.15)),
            max_hold_days=int(exits_cfg.get("max_hold_days", 3)),
            candidate_event_id=ev.get("event_id"),
        )
        summary["accepted"] += 1
        entered = list(state.get("entered_today") or [])
        if symbol not in entered:
            entered.append(symbol)
        state["entered_today"] = entered
        state["daily_entries_count"] = int(
            state.get("daily_entries_count", 0)
        ) + 1
        state["gross_exposure_dollars"] = float(
            state.get("gross_exposure_dollars", 0.0)
        ) + target_notional

        # Execution-quality stub on submit. Phase 6 wires fill data.
        emit_order_execution_quality(cfg, {
            "ts": _iso(now), "symbol": symbol,
            "candidate_event_id": ev.get("event_id"),
            "decision_event_id": accept["event_id"],
            "bid": quote.get("bid"), "ask": quote.get("ask"),
            "mid": quote.get("mid"),
            "spread_pct": quote.get("spread_pct"),
            "quote_timestamp": quote.get("quote_timestamp"),
            "quote_age_seconds": quote.get("quote_age_seconds"),
            "qty": qty,
            "submit_order_style": (cfg.get("execution") or {}).get(
                "parent_order_style", "market",
            ),
        })

    state["last_consumed_event_offset"] = new_offset
    return summary


def _resolve(cfg: dict, key: str, default: Path) -> Path:
    p = (cfg.get("paths") or {}).get(key)
    if not p:
        return default
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return paths.REPO_ROOT / pp


# ---------------------------------------------------------------- post-fill plumbing
# Wires OCO bracket attach, fill polling, exits, kill switches against
# the live OpenAlgo /api/v2 endpoints. The contract follows v1's
# bowaka_strategy module 1:1 — same order role naming, same
# idempotency guarantees, same closure-record shape — but routed
# through the v2 state schema and the bowaka_v2_openalgo_client
# wrappers.


_FILLED_STATUSES = {"filled", "FILLED"}
_DEAD_STATUSES = {
    "canceled", "cancelled", "rejected", "expired", "replaced",
    "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED",
    "done_for_day", "DONE_FOR_DAY",
}


def _emit_ledger_v2(cfg: dict, event_type: str, payload: dict) -> None:
    """Append an event to the v2 trade ledger."""
    ledger_path = _resolve(cfg, "trade_ledger_path", paths.V2_LEDGER_PATH)
    _append_jsonl(ledger_path, {
        "ts": _iso(_now_utc()),
        "event_type": event_type,
        **payload,
    })


def _append_closure_summary(cfg: dict, record: dict) -> None:
    path = _resolve(cfg, "daily_summary_path", paths.V2_DAILY_SUMMARY_PATH)
    _append_jsonl(path, record)


def record_pending_position(
    state: dict,
    *,
    symbol: str,
    qty: int,
    venue_code: str,
    parent_order_id: str,
    link_id: str,
    candidate_close: float | None,
    signal_strength: float | None,
    equity_at_entry: float | None,
    entry_features: dict | None,
    stop_pct: float,
    target_pct: float,
    max_hold_days: int,
    candidate_event_id: str | None,
) -> dict:
    """Write a pending-fill position dict into state['open_positions'].
    Returns the position dict. Called immediately after a successful
    parent submit so poll_fills can match the subsequent fill back to
    the candidate."""
    pos = {
        "symbol": symbol,
        "qty": qty,
        "venue_code": venue_code,
        "parent_order_id": parent_order_id,
        "link_id": link_id,
        "child_order_ids": {"target": "", "stop": ""},
        "status": "pending_fill",
        "entry_price": None,
        "entry_timestamp": _iso(_now_utc()),
        "candidate_close": candidate_close,
        "signal_strength": signal_strength,
        "equity_at_entry": equity_at_entry,
        "entry_features": entry_features or {},
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "max_hold_days": max_hold_days,
        "bracket_pricing_mode": "actual_fill",
        "candidate_event_id": candidate_event_id,
        "entry_trigger": "forming_daily_bar_scan",
        "peak_since_entry": None,
        "trough_since_entry": None,
        "oco_attach_attempts": 0,
    }
    state.setdefault("open_positions", {})[symbol] = pos
    return pos


def _build_order_index_v2(state: dict) -> dict[str, tuple[str, str]]:
    """Map order_id -> (symbol, role) for active orders only.

    Mirrors v1's _build_order_index. We only index the parent
    while the position is in a pre-fill state so a duplicate broker
    echo for an already-FILLED parent doesn't re-trigger parent-fill
    handling.
    """
    idx: dict[str, tuple[str, str]] = {}
    for symbol, pos in (state.get("open_positions") or {}).items():
        if pos.get("status") in {"pending_fill", "submitted", "pending_entry"}:
            pid = pos.get("parent_order_id")
            if pid:
                idx[pid] = (symbol, "parent")
        for role, oid in (pos.get("child_order_ids") or {}).items():
            if oid:
                idx[oid] = (symbol, role)
        eid = pos.get("exit_order_id")
        if eid:
            idx[eid] = (symbol, "exit")
    return idx


def submit_oco_children_v2(
    symbol: str,
    pos: dict,
    cfg: dict,
    *,
    oa_client,
    api_key: str,
    http,
) -> dict | None:
    """Submit an OCO target/stop bracket against an already-filled
    parent position. Idempotent on retry (short-circuits when both
    child IDs are set)."""
    children = pos.get("child_order_ids") or {}
    if children.get("target") and children.get("stop"):
        return None
    entry_price = pos.get("entry_price")
    qty = int(pos.get("qty") or 0)
    venue = pos.get("venue_code") or (cfg.get("execution") or {}).get(
        "default_venue_code", "XNAS",
    )
    target_pct = float(pos.get("target_pct") or 0.15)
    stop_pct = float(pos.get("stop_pct") or 0.08)
    if not entry_price or entry_price <= 0 or qty <= 0:
        LOG.warning(
            "submit_oco_children_v2: %s missing entry_price/qty; "
            "skipping (will retry next tick)", symbol,
        )
        return None
    pos["oco_attach_attempts"] = int(pos.get("oco_attach_attempts", 0)) + 1
    target_price = round(float(entry_price) * (1.0 + target_pct), 2)
    stop_price = round(float(entry_price) * (1.0 - stop_pct), 2)
    link_id = f"{pos.get('link_id', symbol)}-OCO-{int(time.time())}"
    oco_tif = (cfg.get("exits") or {}).get("oco_time_in_force", "GTC")
    parsed = oa_client.submit_oco_bracket(
        http, api_key,
        venue_code=venue, symbol=symbol, qty=qty,
        target_price=target_price, stop_price=stop_price,
        link_id=link_id, time_in_force=oco_tif,
    )
    status = parsed.get("_http_status")
    if status != 200:
        err = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
        LOG.error(
            "OCO bracket submission failed for %s (HTTP %s): %s",
            symbol, status, err,
        )
        return {"error": err, "status": status}
    data = parsed.get("data") or {}
    native = data.get("native_response") or {}
    legs = native.get("legs") or []
    parent_response_id = native.get("id") or native.get("order_id") or ""
    target_id = ""
    stop_id = ""
    for leg in legs:
        otype = (leg.get("order_type") or leg.get("type") or "").lower()
        if "limit" in otype and not target_id:
            target_id = leg.get("id") or leg.get("order_id") or ""
        elif "stop" in otype and not stop_id:
            stop_id = leg.get("id") or leg.get("order_id") or ""
    if not target_id and parent_response_id:
        target_id = parent_response_id
    if not stop_id and len(legs) >= 1:
        stop_id = legs[0].get("id") or ""
    pos["child_order_ids"] = {"target": target_id, "stop": stop_id}
    pos["target_price"] = target_price
    pos["stop_price"] = stop_price
    pos["oco_attached_at"] = _iso(_now_utc())
    _emit_ledger_v2(cfg, "bracket_attached", {
        "symbol": symbol, "link_id": pos.get("link_id"),
        "target_id": target_id, "stop_id": stop_id,
        "target_price": target_price, "stop_price": stop_price,
    })
    emit_protection_state(cfg, {
        "ts": _iso(_now_utc()), "symbol": symbol,
        "event": "bracket_attached",
        "target_id": target_id, "stop_id": stop_id,
        "target_price": target_price, "stop_price": stop_price,
    })
    LOG.info(
        "OCO bracket attached: %s entry=%.4f target=%.2f(%s) stop=%.2f(%s)",
        symbol, float(entry_price), target_price, target_id,
        stop_price, stop_id,
    )
    return parsed


def submit_pending_oco_children_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """Sweep every filled position that doesn't yet have an OCO
    bracket and submit one. Returns the list of symbols that received
    a fresh bracket this call."""
    out: list[str] = []
    for symbol, pos in list((state.get("open_positions") or {}).items()):
        if pos.get("status") != "filled":
            continue
        children = pos.get("child_order_ids") or {}
        if children.get("target") and children.get("stop"):
            continue
        try:
            res = submit_oco_children_v2(
                symbol, pos, cfg,
                oa_client=oa_client, api_key=api_key, http=http,
            )
        except Exception as e:
            LOG.exception(
                "submit_oco_children_v2 raised for %s: %s", symbol, e,
            )
            continue
        if res and "error" not in res:
            out.append(symbol)
    return out


def poll_fills_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[dict]:
    """GET /api/v2/orders?status=all and reconcile fills against state.
    Updates state in place. Returns the list of detected fill events
    (each: ``{symbol, order_id, role, status, filled_qty,
    filled_avg_price}``)."""
    if not state.get("open_positions"):
        return []
    try:
        rows = oa_client.fetch_all_orders(http, api_key)
    except Exception as e:
        LOG.warning("poll_fills_v2 fetch failed: %s", e)
        return []
    idx = _build_order_index_v2(state)
    events: list[dict] = []
    open_positions = state.setdefault("open_positions", {})
    for row in rows:
        oid = row.get("id") or row.get("order_id") or ""
        if oid not in idx:
            continue
        symbol, role = idx[oid]
        pos = open_positions.get(symbol)
        if pos is None:
            continue
        native_status = row.get("native_status") or row.get("status") or ""
        canonical = (
            row.get("canonical_status") or native_status or ""
        ).upper()
        filled_qty = int(float(
            row.get("filled_qty") or row.get("filled_quantity") or 0,
        ))
        filled_avg = row.get("filled_avg_price")
        try:
            filled_avg_f = (
                float(filled_avg) if filled_avg is not None else None
            )
        except (ValueError, TypeError):
            filled_avg_f = None
        ev = {
            "symbol": symbol, "order_id": oid, "role": role,
            "status": canonical, "filled_qty": filled_qty,
            "filled_avg_price": filled_avg_f, "raw": row,
        }
        if role == "parent":
            if (native_status in _FILLED_STATUSES
                    or canonical == "FILLED"):
                if pos.get("parent_fill_processed"):
                    continue
                pos["status"] = "filled"
                pos["entry_price"] = filled_avg_f or pos.get("entry_price")
                if filled_qty > 0:
                    pos["qty"] = filled_qty
                pos["parent_fill_processed"] = True
                pos["parent_fill_processed_at"] = _iso(_now_utc())
                ep = pos.get("entry_price")
                if ep is not None and pos.get("peak_since_entry") is None:
                    pos["peak_since_entry"] = float(ep)
                    pos["trough_since_entry"] = float(ep)
                _emit_ledger_v2(cfg, "entry_fill", {
                    "symbol": symbol, "order_id": oid,
                    "filled_qty": filled_qty,
                    "filled_avg_price": filled_avg_f,
                    "link_id": pos.get("link_id"),
                })
                events.append(ev)
            elif (native_status in _DEAD_STATUSES
                  or canonical in {s.upper() for s in _DEAD_STATUSES}):
                if filled_qty > 0 and not pos.get("parent_fill_processed"):
                    pos["status"] = "filled"
                    pos["entry_price"] = (
                        filled_avg_f or pos.get("entry_price")
                    )
                    pos["qty"] = filled_qty
                    pos["parent_fill_processed"] = True
                    pos["parent_fill_processed_at"] = _iso(_now_utc())
                    events.append(ev)
                else:
                    LOG.info(
                        "parent %s ended in %s — dropping position",
                        symbol, canonical,
                    )
                    open_positions.pop(symbol, None)
                    _emit_ledger_v2(cfg, "parent_terminal", {
                        "symbol": symbol, "order_id": oid,
                        "status": canonical,
                    })
        elif role in ("target", "stop"):
            if (native_status in _FILLED_STATUSES
                    or canonical == "FILLED"):
                pos.setdefault("filled_children", {})[role] = {
                    "filled_qty": filled_qty,
                    "filled_avg_price": filled_avg_f,
                }
                events.append(ev)
        elif role == "exit":
            if (native_status in _FILLED_STATUSES
                    or canonical == "FILLED"):
                pos["exit_fill_price"] = filled_avg_f
                pos["exit_filled_qty"] = filled_qty
                events.append(ev)
    return events


def _trading_days_since(entry_iso: str, today_et: date) -> int:
    """Coarse trading-days-elapsed using pd.bdate_range (Mon-Fri,
    no holiday calendar). Good enough for max_hold_days policy; v2's
    holiday-aware version lands with the venue calendar."""
    try:
        entry_dt = pd.Timestamp(entry_iso)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.tz_localize("UTC")
        entry_d = entry_dt.tz_convert("America/New_York").date()
    except Exception:
        return 0
    if entry_d >= today_et:
        return 0
    days = pd.bdate_range(entry_d, today_et)
    return max(0, len(days) - 1)


def close_position_v2(
    symbol: str,
    state: dict,
    cfg: dict,
    *,
    exit_price: float,
    reason: str,
) -> dict | None:
    """Compute realized PnL, append a closure record to the v2 daily
    summary + ledger, then drop the position from state."""
    pos = (state.get("open_positions") or {}).get(symbol)
    if pos is None:
        return None
    entry_price = float(pos.get("entry_price") or 0.0)
    qty = int(pos.get("qty") or 0)
    realized = (float(exit_price) - entry_price) * qty
    entry_iso = pos.get("entry_timestamp")
    exit_iso = _iso(_now_utc())
    hold_trading_days = None
    if entry_iso:
        try:
            today_et = (
                pd.Timestamp.now(tz="America/New_York").date()
            )
            hold_trading_days = _trading_days_since(entry_iso, today_et)
        except Exception:
            hold_trading_days = None
    peak = pos.get("peak_since_entry")
    trough = pos.get("trough_since_entry")
    try:
        peak_f = float(peak) if peak is not None else None
        trough_f = float(trough) if trough is not None else None
    except (TypeError, ValueError):
        peak_f = trough_f = None
    record = {
        "record_type": "closure",
        "symbol": symbol,
        "qty": qty,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "entry_timestamp": entry_iso,
        "exit_timestamp": exit_iso,
        "realized_pnl": realized,
        "reason": reason,
        "venue_code": pos.get("venue_code"),
        "link_id": pos.get("link_id"),
        "candidate_event_id": pos.get("candidate_event_id"),
        "signal_strength": pos.get("signal_strength"),
        "candidate_close": pos.get("candidate_close"),
        "target_pct": pos.get("target_pct"),
        "stop_pct": pos.get("stop_pct"),
        "target_price": pos.get("target_price"),
        "stop_price": pos.get("stop_price"),
        "hold_trading_days": hold_trading_days,
        "peak_since_entry": peak_f,
        "trough_since_entry": trough_f,
        "entry_trigger": pos.get("entry_trigger"),
    }
    _append_closure_summary(cfg, record)
    _emit_ledger_v2(cfg, "closure", record)
    # Update strategy-tracked PnL + gross exposure.
    state["daily_realized_pnl_strategy"] = float(
        state.get("daily_realized_pnl_strategy", 0.0)
    ) + realized
    notional = entry_price * qty
    state["gross_exposure_dollars"] = max(
        0.0, float(state.get("gross_exposure_dollars", 0.0)) - notional,
    )
    state["open_positions"].pop(symbol, None)
    LOG.info(
        "closed %s: %s pnl=%.2f hold_td=%s entry=%.4f exit=%.4f",
        symbol, reason, realized, hold_trading_days,
        entry_price, float(exit_price),
    )
    return record


def process_fill_events_v2(
    events: list[dict], state: dict, cfg: dict,
) -> list[dict]:
    """Map child/exit fill events to closures."""
    out: list[dict] = []
    open_positions = state.get("open_positions") or {}
    for ev in events:
        symbol = ev["symbol"]
        pos = open_positions.get(symbol)
        if pos is None:
            continue
        role = ev["role"]
        if role == "target" and ev["status"] in {"FILLED"}:
            price = ev["filled_avg_price"] or pos.get("target_price") or 0.0
            rec = close_position_v2(
                symbol, state, cfg,
                exit_price=float(price), reason="target_hit",
            )
            if rec:
                out.append(rec)
        elif role == "stop" and ev["status"] in {"FILLED"}:
            price = ev["filled_avg_price"] or pos.get("stop_price") or 0.0
            rec = close_position_v2(
                symbol, state, cfg,
                exit_price=float(price), reason="stop_hit",
            )
            if rec:
                out.append(rec)
        elif role == "exit" and ev["status"] in {"FILLED"}:
            price = (
                ev["filled_avg_price"]
                or pos.get("exit_fill_price") or 0.0
            )
            exit_reason = pos.get("exit_reason") or "time_stop"
            rec = close_position_v2(
                symbol, state, cfg,
                exit_price=float(price), reason=exit_reason,
            )
            if rec:
                out.append(rec)
    return out


def trigger_exit_v2(
    symbol: str,
    pos: dict,
    cfg: dict,
    *,
    oa_client, api_key: str, http,
    reason: str = "time_stop",
    time_in_force: str = "DAY",
) -> bool:
    """Cancel any OCO children and submit a SELL MARKET exit.
    Returns True iff the broker accepted the market-sell. Idempotent:
    no-op when status != 'filled'."""
    if pos.get("status") != "filled":
        LOG.info(
            "exit for %s already in flight (status=%s reason=%s) — skipping",
            symbol, pos.get("status"), reason,
        )
        return False
    # Reserve before any I/O so a re-entrant tick doesn't double-fire.
    pos["status"] = "exit_pending"
    pos["exit_reason_pending"] = reason
    pos["exit_pending_at"] = _iso(_now_utc())
    children = pos.get("child_order_ids") or {}
    for role in ("target", "stop"):
        oid = children.get(role)
        if not oid:
            continue
        try:
            oa_client.cancel_order(http, api_key, oid)
        except Exception as e:
            LOG.warning(
                "cancel %s child %s failed (continuing): %s",
                symbol, role, e,
            )
    venue = pos.get("venue_code") or (cfg.get("execution") or {}).get(
        "default_venue_code", "XNAS",
    )
    try:
        resp = oa_client.submit_market_sell(
            http, api_key, venue_code=venue, symbol=symbol,
            qty=int(pos["qty"]), time_in_force=time_in_force,
        )
    except Exception as e:
        LOG.exception(
            "market-sell submission failed for %s: %s", symbol, e,
        )
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        return False
    http_status = (resp or {}).get("_http_status") if isinstance(
        resp, dict,
    ) else None
    if http_status not in (200, 201):
        LOG.error(
            "market-sell rejected for %s (status=%s); reverting to "
            "'filled' so the next pass can retry: %s",
            symbol, http_status, resp,
        )
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        return False
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    exit_id = data.get("order_id") or data.get("id") or ""
    if not exit_id:
        LOG.error(
            "market-sell accepted for %s but no order_id surfaced; "
            "reverting: %s", symbol, resp,
        )
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        return False
    pos["status"] = "exiting"
    pos["exit_reason"] = reason
    pos["exit_order_id"] = exit_id
    pos["exit_submitted_at"] = _iso(_now_utc())
    pos.pop("exit_reason_pending", None)
    pos.pop("exit_pending_at", None)
    _emit_ledger_v2(cfg, "exit_submitted", {
        "symbol": symbol, "exit_order_id": exit_id,
        "reason": reason, "time_in_force": time_in_force,
        "link_id": pos.get("link_id"),
    })
    return True


def run_time_stop_pass_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """Walk filled positions; exit those whose hold has reached
    max_hold_days. Returns the list of symbols time-stopped this
    pass."""
    out: list[str] = []
    max_hold = int((cfg.get("exits") or {}).get("max_hold_days", 3))
    today_et = pd.Timestamp.now(tz="America/New_York").date()
    for symbol, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") != "filled":
            continue
        entry_iso = pos.get("entry_timestamp") or ""
        elapsed = _trading_days_since(entry_iso, today_et)
        if elapsed >= max_hold:
            ok = trigger_exit_v2(
                symbol, pos, cfg,
                oa_client=oa_client, api_key=api_key, http=http,
                reason="time_stop", time_in_force="DAY",
            )
            if ok:
                out.append(symbol)
    return out


def execute_kill_l2_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """L2 (KILL_SOFT.flag): market-out every position. For
    pending-fill positions, best-effort cancel parent + children."""
    state["kill_switch_state"] = "L2"
    out: list[str] = []
    for symbol, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "exiting":
            continue
        if pos.get("status") != "filled":
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        oa_client.cancel_order(http, api_key, oid)
                    except Exception:
                        LOG.exception(
                            "L2 cancel %s child %s failed", symbol, role,
                        )
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    oa_client.cancel_order(http, api_key, parent)
                except Exception:
                    LOG.exception("L2 cancel parent %s failed", symbol)
            state["open_positions"].pop(symbol, None)
            out.append(symbol)
            continue
        ok = trigger_exit_v2(
            symbol, pos, cfg,
            oa_client=oa_client, api_key=api_key, http=http,
            reason="kill_switch_l2", time_in_force="DAY",
        )
        if ok:
            out.append(symbol)
    _emit_ledger_v2(cfg, "kill_switch_l2_executed", {
        "symbols_exited": out, "count": len(out),
    })
    return out


def execute_kill_l3_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """L3 (KILL_HARD.flag): best-effort cancel + market-out, then
    caller exits 99."""
    state["kill_switch_state"] = "L3"
    out: list[str] = []
    for symbol, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") == "filled":
            try:
                trigger_exit_v2(
                    symbol, pos, cfg,
                    oa_client=oa_client, api_key=api_key, http=http,
                    reason="kill_switch_l3", time_in_force="DAY",
                )
            except Exception:
                LOG.exception("L3 exit failed for %s — best effort", symbol)
        elif pos.get("status") != "exiting":
            for role in ("target", "stop"):
                oid = (pos.get("child_order_ids") or {}).get(role)
                if oid:
                    try:
                        oa_client.cancel_order(http, api_key, oid)
                    except Exception:
                        LOG.exception(
                            "L3 cancel %s child %s failed", symbol, role,
                        )
            parent = pos.get("parent_order_id")
            if parent:
                try:
                    oa_client.cancel_order(http, api_key, parent)
                except Exception:
                    LOG.exception("L3 cancel parent %s failed", symbol)
        out.append(symbol)
    _emit_ledger_v2(cfg, "kill_switch_l3_executed", {
        "symbols_handled": out, "count": len(out),
    })
    return out


def enforce_protected_position_invariant_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """Phase 4 protected-position safety net. Walks filled positions
    whose OCO bracket is missing; if max_unprotected_seconds has
    elapsed since the parent fill and flatten_if_unprotected is set,
    market-out the position.
    """
    pp = cfg.get("protected_position") or {}
    if not pp.get("enabled", True):
        return []
    max_unprotected = float(pp.get("max_unprotected_seconds", 10))
    flatten = bool(pp.get("flatten_if_unprotected", True))
    out: list[str] = []
    now = _now_utc()
    for symbol, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") != "filled":
            continue
        children = pos.get("child_order_ids") or {}
        if children.get("target") and children.get("stop"):
            continue
        # Use parent_fill_processed_at if present, else entry_timestamp.
        ts_iso = pos.get("parent_fill_processed_at") or pos.get(
            "entry_timestamp",
        )
        try:
            ts = pd.Timestamp(ts_iso)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            age_s = (pd.Timestamp(now) - ts).total_seconds()
        except Exception:
            continue
        if age_s < max_unprotected:
            continue
        emit_protection_state(cfg, {
            "ts": _iso(now), "symbol": symbol,
            "event": "unprotected_position_detected",
            "age_seconds": age_s, "oco_attempts": int(
                pos.get("oco_attach_attempts", 0),
            ),
        })
        if not flatten:
            continue
        ok = trigger_exit_v2(
            symbol, pos, cfg,
            oa_client=oa_client, api_key=api_key, http=http,
            reason="protected_position_flatten", time_in_force="DAY",
        )
        if ok:
            out.append(symbol)
    if out:
        _emit_ledger_v2(cfg, "protected_position_flattened", {
            "symbols": out, "count": len(out),
        })
    return out


# ---------------------------------------------------------------- main


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


_shutdown_requested = False


def _install_signal_handlers() -> None:
    import signal
    def _handler(signum, _frame):
        global _shutdown_requested
        LOG.info("shutdown signal %s received", signum)
        _shutdown_requested = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Some platforms can't install handlers on non-main threads.
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 strategy (event consumer)",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--replay-from", default=None,
        help="Consume an alternative candidate_events.jsonl (test/replay).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process one tick of available events and exit.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run one consume tick then exit (alias for --dry-run "
             "in the loop semantics; useful for cron-style invocation).",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, (cfg.get("logging") or {})
                       .get("level", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        validate_startup_config(cfg)
    except ConfigError as e:
        LOG.error("config error: %s", e)
        return 5

    paths.ensure_dirs()
    persist_config_snapshot(cfg)

    state_path = _resolve(cfg, "state_path", paths.V2_STATE_PATH)
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    else:
        state = {}
    state.setdefault("last_consumed_event_offset", 0)
    state.setdefault("entered_today", [])
    state.setdefault("daily_entries_count", 0)
    state.setdefault("open_positions", {})

    if args.replay_from:
        # Point the consumer at a different candidate-events file.
        cfg.setdefault("paths", {})["candidate_events_path"] = str(
            Path(args.replay_from).resolve()
        )

    one_shot = args.dry_run or args.once or args.replay_from is not None
    if one_shot:
        summary = consume_candidate_events(state, cfg)
        LOG.info("v2 consumer tick: %s", summary)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, default=str, indent=2),
                              encoding="utf-8")
        return 0

    # Long-running loop: consume new candidate events every
    # ``session.loop_interval_seconds`` (default 5) until SIGINT /
    # SIGTERM. The watchdog only re-launches on non-clean exits.
    _install_signal_handlers()
    session_cfg = cfg.get("session") or {}
    interval = int(session_cfg.get("loop_interval_seconds", 5))
    switch_dir = Path((cfg.get("paths") or {}).get("kill_switch_dir", "."))
    if not switch_dir.is_absolute():
        switch_dir = paths.REPO_ROOT / switch_dir

    # Live network suppliers (OpenAlgo /api/v2). Only created when
    # env vars are set; tests without env get a None client and the
    # consumer uses its synthesized-from-signal-price fallback.
    quote_supplier = None
    submit_supplier = None
    live_client = None
    api_key = ""
    try:
        import bowaka_v2_openalgo_client as oa
        host, api_key = oa.resolve_host_and_key()
        live_client = oa.make_http_client(host)
        venue_by_sym = {}  # cached per-symbol venue lookups

        def _venue_for(symbol: str) -> str:
            if symbol in venue_by_sym:
                return venue_by_sym[symbol]
            v = (cfg.get("execution") or {}).get("default_venue_code", "XNAS")
            venue_by_sym[symbol] = v
            return v

        def quote_supplier(symbol: str):  # noqa: F811
            return oa.fetch_quote(
                live_client, api_key,
                venue_code=_venue_for(symbol), symbol=symbol,
            )

        def submit_supplier(symbol: str, qty: int):  # noqa: F811
            return oa.submit_market_buy(
                live_client, api_key,
                venue_code=_venue_for(symbol), symbol=symbol,
                qty=qty, time_in_force="DAY",
            )

        LOG.info("v2 strategy: live OpenAlgo suppliers wired (host=%s)", host)
    except RuntimeError as e:
        LOG.warning(
            "live suppliers NOT wired (%s); running in offline log-only mode",
            e,
        )

    oa_module = None
    try:
        import bowaka_v2_openalgo_client as oa_module  # type: ignore
    except Exception:
        oa_module = None

    LOG.info(
        "v2 strategy entering long-running loop "
        "(interval=%ds, kill_switch_dir=%s)", interval, switch_dir,
    )
    while not _shutdown_requested:
        # L3 hard-kill — drop everything best-effort, persist, exit 99.
        if (switch_dir / "KILL_HARD.flag").exists():
            LOG.error("L3 KILL_HARD flag detected — flattening + exit 99")
            if live_client and oa_module is not None:
                try:
                    execute_kill_l3_v2(
                        state, cfg,
                        oa_client=oa_module, api_key=api_key,
                        http=live_client,
                    )
                except Exception:
                    LOG.exception("L3 cleanup raised (continuing to exit)")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state, default=str, indent=2), encoding="utf-8",
            )
            if live_client:
                live_client.close()
            return 99

        # L2 soft-kill — flatten all but stay alive (operator can clear
        # the flag after manual triage).
        if (switch_dir / "KILL_SOFT.flag").exists():
            if state.get("kill_switch_state") != "L2":
                LOG.error("L2 KILL_SOFT flag detected — flattening positions")
                if live_client and oa_module is not None:
                    try:
                        execute_kill_l2_v2(
                            state, cfg,
                            oa_client=oa_module, api_key=api_key,
                            http=live_client,
                        )
                    except Exception:
                        LOG.exception("L2 flatten raised")
        elif state.get("kill_switch_state") == "L2":
            # Operator cleared the flag — release the L2 mark so future
            # blocks behave normally.
            state.pop("kill_switch_state", None)

        # L1 block-new — KILL_NEW.flag prevents new entries; existing
        # positions keep their brackets / time-stops running.
        l1_block_new = (switch_dir / "KILL_NEW.flag").exists()

        try:
            if not l1_block_new:
                summary = consume_candidate_events(
                    state, cfg,
                    quote_supplier=quote_supplier,
                    submit_supplier=submit_supplier,
                )
                if summary.get("consumed", 0) > 0:
                    LOG.info("v2 consumer tick: %s", summary)
            else:
                LOG.info(
                    "L1 KILL_NEW.flag active — skipping entry consume tick",
                )
        except Exception as e:
            LOG.exception("consume_candidate_events raised: %s", e)

        # Post-fill plumbing: only runs when live network is wired
        # (oa_module + live_client present). In offline / log-only mode
        # there's no broker to poll, so we skip.
        if live_client and oa_module is not None:
            try:
                fills = poll_fills_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
                if fills:
                    process_fill_events_v2(fills, state, cfg)
            except Exception:
                LOG.exception("poll_fills_v2 raised")
            try:
                submit_pending_oco_children_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("submit_pending_oco_children_v2 raised")
            try:
                enforce_protected_position_invariant_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("enforce_protected_position_invariant_v2 raised")
            try:
                run_time_stop_pass_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("run_time_stop_pass_v2 raised")

        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state, default=str, indent=2), encoding="utf-8",
            )
        except Exception as e:
            LOG.warning("state write failed: %s", e)
        # Sleep in small chunks so the shutdown flag is honored quickly.
        slept = 0.0
        while slept < interval and not _shutdown_requested:
            time.sleep(min(0.5, interval - slept))
            slept += 0.5
    if live_client:
        live_client.close()
    LOG.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
