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
from datetime import date, datetime, time as dt_time, timedelta, timezone
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
    """Read new COMPLETE lines from candidate_events.jsonl since
    ``last_offset`` (byte offset). Returns ``(events, new_offset)``.

    Torn-line safe (scanner-hydrate pattern, binary mode): a trailing
    partial line — the scanner mid-append — is NOT consumed; the
    offset stops at the last newline so the line re-reads complete on
    the next tick instead of being parsed torn and lost forever. A
    file smaller than the stored offset (rotation/truncation) resets
    the offset to 0 and re-reads from the top; the stale-session and
    same-symbol dedupe gates make replayed events harmless. A
    malformed COMPLETE line is still skipped with the offset
    advanced."""
    if not candidate_events_path.exists():
        return [], last_offset
    try:
        size = candidate_events_path.stat().st_size
    except OSError:
        return [], last_offset
    offset = max(0, int(last_offset or 0))
    if offset > size:
        LOG.warning(
            "candidate_events file shrank below the stored offset "
            "(%d > %d) — rotation/truncation detected; resetting to 0",
            offset, size,
        )
        offset = 0
    if offset >= size:
        return [], offset
    with open(candidate_events_path, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    cut = chunk.rfind(b"\n")
    if cut < 0:
        # Only a torn partial line so far — consume nothing.
        return [], offset
    complete = chunk[:cut + 1]
    new_offset = offset + cut + 1
    out: list[dict] = []
    for raw in complete.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
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
    # Crossed book (bid > ask) is a halt/stale-feed proxy — a sane
    # live NBBO never crosses. Reject even without real halt status.
    if (isinstance(bid, (int, float)) and isinstance(ask, (int, float))
            and bid > 0 and ask > 0 and bid > ask):
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


_HALT_STATUSES = frozenset({
    "halted", "pending_review", "luld_pause", "inactive",
})


def _halt_gate(symbol_status: str | None, cfg: dict) -> str | None:
    hg = (cfg.get("execution") or {}).get("halt_gate") or {}
    if not hg.get("enabled", True):
        return None
    if not symbol_status:
        return None
    if symbol_status.lower() in _HALT_STATUSES:
        return "halt_or_pending_review"
    return None


def _recent_pause_gate(state: dict, symbol: str, cfg: dict) -> str | None:
    """halt_gate.block_on_recent_luld_pause — once a halt/pause status
    was observed for a symbol this session, block re-entry for the
    rest of the session even after the status clears (LULD pauses
    cluster). The memory map is purged on session rollover."""
    hg = (cfg.get("execution") or {}).get("halt_gate") or {}
    if not hg.get("enabled", True):
        return None
    if not hg.get("block_on_recent_luld_pause", False):
        return None
    if symbol in (state.get("luld_pauses") or {}):
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

    # Idempotency guard — while ANY lot's submit outcome is unknown
    # (resolver still adjudicating whether the order reached the
    # broker), refuse all new entries: sizing, exposure and per-symbol
    # caps can't be trusted until the unknown resolves.
    if any(
        p.get("outcome_unresolved")
        for p in (state.get("open_positions") or {}).values()
    ):
        return "unresolved_order_outcome"

    # bankroll floor — halt ALL new entries once compounding equity has
    # fallen to/below floor_fraction*base. Checked FIRST so it dominates
    # even at negative equity, ahead of the bankroll>0 guarded gates
    # below. No-op unless sizing.compounding.enabled. Exit/management
    # paths never call _risk_gates, so open lots are still managed.
    if _below_floor(state, cfg):
        if not _FLOOR_HALT_WARNED["v"]:
            base = _compounding_base(cfg)
            ff = float((sizing_cfg.get("compounding") or {}).get(
                "floor_fraction", 0.50))
            LOG.warning(
                "bankroll floor halt: effective equity %.2f <= floor %.2f "
                "(%.0f%% of base %.2f) — refusing NEW entries until "
                "realized PnL recovers", _effective_equity(state, cfg),
                ff * base, ff * 100.0, base,
            )
            _FLOOR_HALT_WARNED["v"] = True
        return "bankroll_floor_halt"
    # Recovered above the floor — re-arm the once-per-episode warning so a
    # later dip back below the floor logs again.
    _FLOOR_HALT_WARNED["v"] = False

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

    # Stop-out circuit breakers (v1 parity). daily_stopout_count and
    # consecutive_stopout_count are maintained by close_position_v2.
    max_stopouts = risk_cfg.get("max_stopouts_per_day")
    if max_stopouts is not None:
        if int(state.get("daily_stopout_count", 0) or 0) >= int(max_stopouts):
            return "max_stopouts_per_day"
    max_consecutive = risk_cfg.get("stop_trading_after_consecutive_stopouts")
    if max_consecutive is not None:
        if (int(state.get("consecutive_stopout_count", 0) or 0)
                >= int(max_consecutive)):
            return "consecutive_stopouts"

    # strategy_slice_loss_pct — v1 archive semantics: block new entries
    # once the day's realized PnL crosses -X% of the daily slice
    # (bankroll / max_hold_days). Tighter stop than daily_loss_pct
    # because the slice basis is smaller.
    slice_loss_pct = risk_cfg.get("strategy_slice_loss_pct")
    if slice_loss_pct is not None and bankroll and bankroll > 0:
        max_hold = max(1, int(
            (cfg.get("exits") or {}).get("max_hold_days") or 1,
        ))
        slice_basis = float(bankroll) / float(max_hold)
        pnl = float(state.get("daily_realized_pnl_strategy") or 0.0)
        if slice_basis > 0 and pnl / slice_basis <= -float(slice_loss_pct):
            return "strategy_slice_loss"

    # ADV cap — tiered policy via adv_tier_cap (inlined above).
    # Enforced on the AGGREGATE position in this symbol (existing lots
    # + this candidate) so stacking lots across days cannot blow
    # through the symbol's liquidity limit.
    if candidate_adv is not None and candidate_adv > 0:
        try:
            allowed, cap_dollars = adv_tier_cap(candidate_adv, cfg)
            projected_notional = (
                _symbol_open_notional(state, ev.get("symbol", ""))
                + target_notional
            )
            if not allowed or (
                cap_dollars and projected_notional > cap_dollars
            ):
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

# Module-level once-per-process guard for the bankroll-floor-halt
# warning (so the WARNING is not re-emitted every candidate every tick).
# Deliberately NOT persisted to state -> nothing to reset on rollover.
_FLOOR_HALT_WARNED = {"v": False}


def _compounding_base(cfg: dict) -> float:
    """Starting bankroll the floor/cap multiples are measured against.
    Defaults to sizing.bankroll_fixed_dollars; sizing.compounding.
    base_dollars overrides when explicitly set (non-null)."""
    sizing_cfg = cfg.get("sizing") or {}
    comp = sizing_cfg.get("compounding") or {}
    base = comp.get("base_dollars")
    if base is None:
        base = sizing_cfg.get("bankroll_fixed_dollars", 90000)
    return float(base)


def _effective_equity(state: dict, cfg: dict) -> float:
    """base + lifetime realized strategy PnL (closed trades only)."""
    base = _compounding_base(cfg)
    cum = float((state or {}).get("cumulative_realized_pnl_strategy", 0.0) or 0.0)
    return base + cum


def _ledger_realized_sum(cfg: dict) -> float:
    """Authoritative lifetime realized PnL: sum of realized_pnl over
    every closure record in the append-only daily-summary ledger. Used
    to reconcile the in-state cumulative on load so a torn/lost
    state.json, a .bak restore, or the crash window between a closure's
    ledger append and the next state write cannot silently mis-state the
    compounding bankroll. Returns 0.0 on any read/parse failure."""
    path = _resolve(cfg, "daily_summary_path", paths.V2_DAILY_SUMMARY_PATH)
    total = 0.0
    try:
        if not path.exists():
            return 0.0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("record_type") == "closure":
                rp = rec.get("realized_pnl")
                # bool is a subclass of int — exclude it so a corrupted
                # `realized_pnl: true` can't silently add 1.0.
                if isinstance(rp, (int, float)) and not isinstance(rp, bool):
                    total += float(rp)
    except Exception:
        return 0.0
    return total


def _sizing_bankroll(state: dict, cfg: dict) -> float:
    """Bankroll used for equal-slice sizing. The fixed base unless
    sizing.compounding.enabled, in which case it compounds on cumulative
    realized PnL, clamped to [0, cap_multiple*base]. Realized profit
    beyond the cap stays in the account but does not grow sizing."""
    sizing_cfg = cfg.get("sizing") or {}
    comp = sizing_cfg.get("compounding") or {}
    base = _compounding_base(cfg)
    if not comp.get("enabled"):
        return base
    cap_multiple = float(comp.get("cap_multiple", 4.0))
    effective = _effective_equity(state, cfg)
    return max(0.0, min(effective, cap_multiple * base))


def _below_floor(state: dict, cfg: dict) -> bool:
    """True when compounding is enabled AND effective equity has fallen
    to/below floor_fraction*base -> halt ALL new entries. Exit and
    position-management paths never call this, so open lots are still
    managed and exited while new entries are refused."""
    sizing_cfg = cfg.get("sizing") or {}
    comp = sizing_cfg.get("compounding") or {}
    if not comp.get("enabled"):
        return False
    base = _compounding_base(cfg)
    floor_fraction = float(comp.get("floor_fraction", 0.50))
    return _effective_equity(state, cfg) <= floor_fraction * base


def _reconcile_cumulative_from_ledger(state: dict, cfg: dict) -> None:
    """Authoritatively (re)set the in-state lifetime realized PnL from the
    closure ledger (source of truth). OVERWRITE, not add — so a torn or
    stale state.json, a .bak restore, or the crash window between a
    closure append and the next state write all heal to the true sum on
    load. Legacy state with no field is seeded from the ledger."""
    state["cumulative_realized_pnl_strategy"] = _ledger_realized_sum(cfg)


def _write_state_atomic(state: dict, path: Path) -> None:
    """Persist state via a tmp file + os.replace so a crash mid-write
    cannot corrupt the live state.json (which now also carries the
    compounding cumulative). Mirrors persist_config_snapshot's pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, default=str, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_state_with_recovery(state_path: Path) -> tuple[dict, bool]:
    """Load state.json with recovery fallbacks: the primary file, then
    the atomic-write ``.tmp`` sibling, then the newest daily
    ``.bak_YYYYMMDD`` backup. Returns ``(state, parse_failed)`` where
    ``parse_failed`` is True when the primary existed but NO source
    could be parsed — the caller must then refuse to trade blind if
    the broker reports open positions."""
    if not state_path.exists():
        return {}, False
    candidates: list[tuple[str, Path]] = [("state.json", state_path)]
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    if tmp.exists():
        candidates.append(("state.json.tmp", tmp))
    baks = sorted(
        state_path.parent.glob(state_path.name + ".bak_*"),
        reverse=True,
    )
    candidates.extend((b.name, b) for b in baks)
    for label, p in candidates:
        try:
            state = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            LOG.error("state source %s unreadable: %s", label, e)
            continue
        if not isinstance(state, dict):
            LOG.error("state source %s is not a dict — skipping", label)
            continue
        if label != "state.json":
            LOG.warning(
                "state.json corrupt — recovered state from %s", label,
            )
        return state, False
    LOG.error(
        "state.json corrupt and no usable .tmp/.bak fallback — "
        "starting with empty state (reconciliation will refuse to "
        "trade if the broker holds positions)",
    )
    return {}, True


def _recompute_gross_exposure(state: dict) -> float:
    """Sum of open-lot exposure: each lot's recorded_exposure, falling
    back to qty x (entry_price or candidate_close). Used on session
    rollover and startup so gross_exposure_dollars reflects the lots
    actually held instead of being zeroed under live positions."""
    total = 0.0
    for pos in (state.get("open_positions") or {}).values():
        exp = pos.get("recorded_exposure")
        if (isinstance(exp, (int, float)) and not isinstance(exp, bool)
                and exp > 0):
            total += float(exp)
            continue
        qty = pos.get("qty") or 0
        price = pos.get("entry_price") or pos.get("candidate_close") or 0.0
        try:
            total += float(qty) * float(price)
        except (TypeError, ValueError):
            pass
    return total


def backup_state_daily(
    state: dict, state_path: Path, *, now_et=None, keep: int = 5,
) -> Path | None:
    """Once per ET session date, write ``state.json.bak_<YYYYMMDD>``
    (atomic) and prune to the ``keep`` newest backups. Returns the
    backup path when one was written this call, else None."""
    if now_et is None:
        now_et = pd.Timestamp.now(tz="America/New_York")
    stamp = now_et.date().isoformat().replace("-", "")
    bak = state_path.with_name(state_path.name + f".bak_{stamp}")
    if bak.exists():
        return None
    try:
        _write_state_atomic(state, bak)
    except Exception:
        LOG.exception("daily state backup failed")
        return None
    baks = sorted(state_path.parent.glob(state_path.name + ".bak_*"))
    for old in baks[:-keep] if len(baks) > keep else []:
        try:
            old.unlink()
        except OSError:
            pass
    LOG.info("daily state backup written: %s", bak.name)
    return bak


def size_position(
    ev: dict, cfg: dict, *, current_price: float,
    state: dict | None = None,
    stop_pct: float | None = None,
) -> tuple[int, float]:
    """Equal-slice sizing per cfg.sizing. Returns (qty,
    target_notional). Honors min_order_notional, then the
    max_per_trade_dollars notional cap, then the target_risk_dollars
    qty cap (stop_pct x qty x price <= target_risk_dollars). When
    sizing.compounding.enabled the bankroll compounds on cumulative
    realized PnL (clamped to the cap); otherwise it is the fixed base."""
    sizing_cfg = cfg.get("sizing") or {}
    bankroll = _sizing_bankroll(state or {}, cfg)
    n_slots = int(sizing_cfg.get("max_concurrent_positions", 18))
    frac = float(sizing_cfg.get("equal_slice_bankroll_fraction", 0.80))
    target_notional = frac * bankroll / n_slots
    min_order_notional = float(sizing_cfg.get("min_order_notional", 500))
    if target_notional < min_order_notional:
        target_notional = min_order_notional
    max_per_trade = sizing_cfg.get("max_per_trade_dollars")
    if max_per_trade is not None:
        target_notional = min(target_notional, float(max_per_trade))
    if current_price <= 0:
        return 0, 0.0
    qty = int(target_notional // current_price)
    target_risk = sizing_cfg.get("target_risk_dollars")
    if target_risk is not None and stop_pct and float(stop_pct) > 0:
        risk_per_share = float(stop_pct) * current_price
        if risk_per_share > 0:
            qty = min(qty, int(float(target_risk) // risk_per_share))
    return qty, qty * current_price


# ---- per-symbol dedupe ----


def _symbol_already_entered_today(
    state: dict, symbol: str, cfg: dict | None = None,
) -> bool:
    """True when the symbol has used up its
    scanner.same_symbol_entries_per_day allowance (default 1).
    entered_today records one element per entry, so a count supports
    N > 1."""
    limit = max(1, int(((cfg or {}).get("scanner") or {}).get(
        "same_symbol_entries_per_day", 1,
    ) or 1))
    entered = list(state.get("entered_today") or [])
    return entered.count(symbol) >= limit


def _symbol_in_cooldown(state: dict, symbol: str, now=None) -> bool:
    """True while the symbol's post-stopout cooldown
    (scanner.symbol_cooldown_minutes, written on stop_hit closures)
    is still active."""
    cooldowns = state.get("cooldowns") or {}
    entry = cooldowns.get(symbol)
    if not entry:
        return False
    until = entry.get("until")
    if not until:
        return False
    try:
        u = pd.Timestamp(until)
        if u.tzinfo is None:
            u = u.tz_localize("UTC")
        n = (pd.Timestamp(now) if now is not None
             else pd.Timestamp.now(tz="UTC"))
        if n.tzinfo is None:
            n = n.tz_localize("UTC")
        return n < u
    except Exception:
        return False


def lots_for_symbol(state: dict, symbol: str) -> list[dict]:
    """All open-position lots currently held for ``symbol``. With the
    link_id-keyed ``open_positions`` a symbol may hold several lots
    (one per entry day, capped by ``risk.max_lots_per_symbol``)."""
    return [
        p for p in (state.get("open_positions") or {}).values()
        if p.get("symbol") == symbol
    ]


def _symbol_open_notional(state: dict, symbol: str) -> float:
    """Aggregate dollar exposure already held in ``symbol`` across all
    its open lots. Used so the ADV cap is enforced on the combined
    position, not per-lot."""
    total = 0.0
    for pos in lots_for_symbol(state, symbol):
        qty = float(pos.get("qty") or 0)
        price = pos.get("entry_price") or pos.get("candidate_close") or 0.0
        try:
            total += qty * float(price)
        except (TypeError, ValueError):
            pass
    return total


def _migrate_open_positions(open_positions: dict) -> dict:
    """Re-key ``open_positions`` by each lot's unique ``link_id`` so one
    symbol can hold multiple lots. Idempotent — a no-op once the dict is
    already link_id-keyed. Converts the legacy symbol-keyed shape
    (``{"RUM": {...}}``) to the multi-lot shape
    (``{"BOWAKAv2-RUM-1779375137": {...}}``)."""
    rekeyed: dict = {}
    changed = False
    for k, pos in (open_positions or {}).items():
        new_key = pos.get("link_id") or k
        if new_key != k:
            changed = True
        rekeyed[new_key] = pos
    if changed:
        LOG.info(
            "migrated open_positions to link_id keying (%d lot(s))",
            len(rekeyed),
        )
    return rekeyed


# ---- consumer entry point ----


def _supplier_accepts_quote(supplier) -> bool:
    """True when a submit_supplier accepts a third (quote) parameter.
    Determined once via signature inspection so a TypeError raised
    INSIDE the supplier is never mistaken for a 2-arg signature."""
    return _supplier_positional_arity(supplier) >= 3


def _supplier_positional_arity(supplier) -> int:
    """Effective positional-parameter count of a submit_supplier for
    backward-compatible dispatch: >=4 → (symbol, qty, quote, link_id),
    3 → (symbol, qty, quote), else (symbol, qty). VAR_POSITIONAL
    counts as unbounded (4). Signature inspection — never probing —
    so a TypeError raised INSIDE the supplier is never mistaken for
    a smaller signature."""
    import inspect
    try:
        params = inspect.signature(supplier).parameters
    except (TypeError, ValueError):
        return 2
    if any(p.kind == p.VAR_POSITIONAL for p in params.values()):
        return 4
    positional = [
        p for p in params.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional)


def roll_session_if_needed(
    state: dict, now_utc: datetime, today_iso: str,
) -> bool:
    """Session rollover — when the ET date crosses from a recorded
    prior session to today, reset per-day counters so daily caps
    don't accumulate across sessions. We never reset
    last_consumed_event_offset; candidate_events.jsonl is append-
    only across sessions and stale-session-rejection handles
    leftover events. First run (no recorded session_date) leaves
    state alone — caller-provided seeds are respected.

    Extracted from consume_candidate_events so the main loop can roll
    the session even on ticks that skip the consume pass (L1 KILL_NEW
    active) — otherwise entered_today / daily caps would leak into
    the next session for as long as the flag stayed up. Returns True
    when a rollover happened."""
    prior_session = state.get("session_date")
    if prior_session is None:
        state["session_date"] = today_iso
        return False
    if prior_session == today_iso:
        return False
    state["session_date"] = today_iso
    state["entered_today"] = []
    state["daily_entries_count"] = 0
    state["daily_realized_pnl_strategy"] = 0.0
    state["daily_stopout_count"] = 0
    # consecutive_stopout_count deliberately NOT reset by rollover —
    # only a non-stop closure clears the streak (v1 parity).
    # Purge expired symbol cooldowns; keep any still active.
    cooldowns = state.get("cooldowns") or {}
    if cooldowns:
        state["cooldowns"] = {
            s: c for s, c in cooldowns.items()
            if _symbol_in_cooldown({"cooldowns": {s: c}}, s, now_utc)
        }
    # Per-scan accept counters and the LULD-pause memory are
    # session-scoped.
    state.pop("scan_accept_counts", None)
    state.pop("luld_pauses", None)
    # Gross exposure is NOT a per-day counter — lots held overnight
    # keep their exposure. Recompute from the open lots instead of
    # zeroing (which under-counted risk gates all next session).
    state["gross_exposure_dollars"] = _recompute_gross_exposure(state)
    return True


def consume_candidate_events(
    state: dict,
    cfg: dict,
    *,
    quote_supplier=None,
    submit_supplier=None,
    now_utc: datetime | None = None,
    today_iso: str | None = None,
    state_path: Path | None = None,
) -> dict[str, int]:
    """Read new candidate events since the last consumed offset and
    apply gates → submit entries or emit rejection events. Returns
    summary counts.

    ``quote_supplier(symbol) -> dict | None`` and ``submit_supplier
    (symbol, qty) -> dict`` are injection points for tests.
    ``today_iso`` defaults to the wall-clock ET date; pass it
    explicitly when working from a fixture session date. When
    ``state_path`` is set, state is persisted atomically after EACH
    accepted live submit so a crash between the submit and the end-
    of-tick state write cannot replay the entry as a duplicate order.
    """
    now = now_utc or _now_utc()
    today_iso = today_iso or _today_iso()

    roll_session_if_needed(state, now, today_iso)

    # Normalize open_positions to the link_id-keyed multi-lot shape
    # (idempotent — converts legacy symbol-keyed state on first load).
    if state.get("open_positions"):
        state["open_positions"] = _migrate_open_positions(
            state["open_positions"]
        )

    cand_path = _resolve(cfg, "candidate_events_path",
                          paths.CANDIDATE_EVENTS_PATH)
    last_offset = int(state.get("last_consumed_event_offset", 0))
    events, new_offset = tail_new_events(cand_path, last_offset)

    summary = {
        "consumed": 0, "accepted": 0, "rejected": 0,
        "expired": 0, "stale": 0, "dedupe": 0, "invalid": 0,
        "unresolved": 0,
    }

    # scanner.max_entries_per_scan — accept at most N candidates per
    # scan batch, lowest candidate_rank first. Counters persist in
    # state so a scan burst split across two consume ticks still
    # honors the cap; pruned on session rollover.
    max_per_scan = (cfg.get("scanner") or {}).get("max_entries_per_scan")
    scan_accepts: dict[str, int] = state.setdefault(
        "scan_accept_counts", {},
    )

    def _rank_key(e: dict):
        try:
            rank = float(e.get("candidate_rank"))
        except (TypeError, ValueError):
            rank = float("inf")
        return (str(e.get("scan_timestamp") or ""), rank)

    events = sorted(events, key=_rank_key)

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
        # Same-symbol dedupe — scanner.same_symbol_entries_per_day
        # entries per symbol per day (default 1).
        if _symbol_already_entered_today(state, symbol, cfg):
            summary["dedupe"] += 1
            rec = build_rejection_record(
                ev, reason="same_symbol_already_entered_today",
                decision_ts=now,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Post-stopout cooldown (scanner.symbol_cooldown_minutes).
        if _symbol_in_cooldown(state, symbol, now):
            summary["rejected"] += 1
            rec = build_rejection_record(
                ev, reason="symbol_cooldown", decision_ts=now,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Multi-lot cap. A symbol may be re-entered on consecutive days
        # (same-day re-entry is blocked above) up to
        # risk.max_lots_per_symbol concurrent lots.
        max_lots = int((cfg.get("risk") or {}).get("max_lots_per_symbol", 3))
        if len(lots_for_symbol(state, symbol)) >= max_lots:
            summary["dedupe"] += 1
            rec = build_rejection_record(
                ev, reason="max_lots_per_symbol", decision_ts=now,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        signal_price = (
            ev.get("forming_session_bar", {}).get("last_price")
        )
        # A missing/zero signal price must reject outright — never mask
        # it with a $1.00 sizing fallback (which would size a maximal
        # qty off a fictitious price).
        if (not isinstance(signal_price, (int, float))
                or isinstance(signal_price, bool)
                or float(signal_price) <= 0):
            summary["rejected"] += 1
            rec = build_rejection_record(
                ev, reason="invalid_signal_price", decision_ts=now,
            )
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue
        signal_price = float(signal_price)
        adv = (ev.get("prior_daily_baselines") or {}).get(
            "avg_dollar_volume_20d"
        )
        qty, target_notional = size_position(
            ev, cfg, current_price=signal_price, state=state,
            stop_pct=(cfg.get("exits") or {}).get("stop_pct"),
        )
        if qty <= 0:
            summary["rejected"] += 1
            rec = build_rejection_record(ev, reason="adv_cap",
                                          decision_ts=now)
            emit_entry_decision_v2(cfg, rec)
            emit_rejected_candidate(cfg, rec)
            continue

        # Quote gate. Live mode (quote_supplier wired): a failed fetch
        # rejects the candidate — never synthesize a perfect quote
        # around a real order. Offline (quote_supplier is None): a
        # synthesized quote is acceptable because no order can be
        # placed without a submit_supplier.
        if quote_supplier is not None:
            quote = quote_supplier(symbol)
            if quote is None:
                summary["rejected"] += 1
                rec = build_rejection_record(
                    ev, reason="quote_stale", decision_ts=now,
                )
                emit_entry_decision_v2(cfg, rec)
                emit_rejected_candidate(cfg, rec)
                continue
        else:
            quote = {
                "bid": signal_price, "ask": signal_price,
                "mid": signal_price, "spread_pct": 0.0,
                "quote_timestamp": _iso(now), "quote_age_seconds": 0,
            }
        # LULD/halt memory: any halt-shaped status observed for the
        # symbol is remembered for the rest of the session. When the
        # adapter reports no status at all, note (once per session)
        # that true halt detection is degraded to the quote proxies.
        symbol_status = quote.get("symbol_status")
        if (symbol_status
                and str(symbol_status).lower() in _HALT_STATUSES):
            state.setdefault("luld_pauses", {})[symbol] = _iso(now)
        elif (not symbol_status
                and (cfg.get("execution") or {}).get(
                    "halt_gate", {}).get("enabled", True)
                and state.get(
                    "halt_status_unavailable_logged_on") != today_iso):
            state["halt_status_unavailable_logged_on"] = today_iso
            LOG.info(
                "quotes carry no trading status — halt gate is running "
                "on crossed/zero-quote proxies only this session",
            )

        rejection = _quote_gate(quote, cfg)
        if rejection is None:
            rejection = _price_chase_gate(quote, signal_price or 0.0, cfg)
        if rejection is None:
            rejection = _halt_gate(symbol_status, cfg)
        if rejection is None:
            rejection = _recent_pause_gate(state, symbol, cfg)
        if rejection is None:
            # Risk gates.
            rejection = _risk_gates(
                ev, state, cfg,
                candidate_adv=adv, target_notional=target_notional,
            )

        risk_snapshot = {
            # Telemetry only — the actual bankroll used for sizing
            # (compounded when enabled, else base). The risk gates above
            # are deliberately NOT driven by this; they stay anchored to
            # the base via their own fixed fallback.
            "bankroll": _sizing_bankroll(state, cfg),
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

        # scanner.max_entries_per_scan — checked after all other gates
        # so rejected candidates don't consume scan slots. Events are
        # processed lowest candidate_rank first (sorted above).
        scan_key = str(ev.get("scan_timestamp") or "")
        if (max_per_scan is not None
                and scan_accepts.get(scan_key, 0) >= int(max_per_scan)):
            summary["rejected"] += 1
            rec = build_rejection_record(
                ev, reason="max_entries_per_scan", decision_ts=now,
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
        if submit_supplier is None:
            # Offline / --once / --replay-from / creds-missing mode:
            # decision telemetry only. A phantom position with an
            # empty parent_order_id can never be matched to a fill,
            # so no position is recorded and no counters move.
            accept["execution"] = "skipped_no_supplier"
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

        if submit_supplier is None:
            summary["accepted"] += 1
            scan_accepts[scan_key] = scan_accepts.get(scan_key, 0) + 1
            continue

        # link_id doubles as the broker-side client_order_id, so it is
        # generated BEFORE the submit — a crash-replayed duplicate of
        # the same submit is then rejected by the broker instead of
        # double-buying. Nanosecond resolution keeps keys unique.
        venue_code = (cfg.get("execution") or {}).get(
            "default_venue_code", "XNAS",
        )
        link_id = f"BOWAKAv2-{symbol}-{time.time_ns()}"

        def _record_lot(parent_id: str) -> dict:
            record_pending_position(
                state,
                symbol=symbol, qty=qty, venue_code=venue_code,
                parent_order_id=parent_id, link_id=link_id,
                candidate_close=signal_price, signal_strength=ev.get(
                    "signal_strength",
                ),
                recorded_exposure=target_notional,
                equity_at_entry=risk_snapshot.get("bankroll"),
                entry_features=ev.get("features"),
                prior_daily_baselines=ev.get("prior_daily_baselines"),
                parent_order_style=(cfg.get("execution") or {}).get(
                    "parent_order_style", "market",
                ),
                stop_pct=float(exits_cfg.get("stop_pct", 0.08)),
                target_pct=float(exits_cfg.get("target_pct", 0.15)),
                max_hold_days=int(exits_cfg.get("max_hold_days", 3)),
                candidate_event_id=ev.get("event_id"),
            )
            return state["open_positions"][link_id]

        # Submit order (injection point). Suppliers that accept a
        # third parameter receive the live quote so marketable-limit
        # entries can price off the ask; 4-arg suppliers additionally
        # receive the link_id to send as the broker client_order_id;
        # 2-arg test suppliers keep their legacy signature.
        parent_order_id = ""
        unresolved_detail = ""
        submit_resp = None
        arity = _supplier_positional_arity(submit_supplier)
        try:
            if arity >= 4:
                submit_resp = submit_supplier(symbol, qty, quote, link_id)
            elif arity == 3:
                submit_resp = submit_supplier(symbol, qty, quote)
            else:
                submit_resp = submit_supplier(symbol, qty)
        except Exception as e:
            # The order may or may not have reached the broker —
            # outcome UNKNOWN. Never drop the event silently: record
            # an unresolved lot keyed by the client_order_id and let
            # resolve_unknown_submits adjudicate.
            LOG.warning(
                "submit_supplier raised for %s: %s — outcome unknown, "
                "recording unresolved lot", symbol, e,
            )
            unresolved_detail = f"exception: {e}"
        if not unresolved_detail:
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
                # Clean broker rejection — no shares, no lot.
                summary["rejected"] += 1
                continue
            if not parent_order_id:
                LOG.warning(
                    "submit for %s accepted with no order id — outcome "
                    "unknown, recording unresolved lot", symbol,
                )
                unresolved_detail = "accepted_no_order_id"

        if unresolved_detail:
            pos = _record_lot("")
            pos["outcome_unresolved"] = True
            pos["resolver_misses"] = 0
            summary["unresolved"] += 1
            _emit_ledger_v2(cfg, "submit_outcome_unknown", {
                "symbol": symbol, "link_id": link_id,
                "client_order_id": link_id,
                "detail": unresolved_detail,
            })
        else:
            _record_lot(parent_order_id)
            summary["accepted"] += 1
        scan_accepts[scan_key] = scan_accepts.get(scan_key, 0) + 1
        # One element per entry (not a set) so
        # same_symbol_entries_per_day > 1 can count correctly.
        state["entered_today"] = list(
            state.get("entered_today") or []
        ) + [symbol]
        if (cfg.get("logging") or {}).get("emit_feature_snapshots", False):
            _append_jsonl(paths.FEATURE_SNAPSHOTS_PATH, {
                "ts": _iso(now), "symbol": symbol,
                "session_date": ev.get("session_date"),
                "candidate_event_id": ev.get("event_id"),
                "link_id": link_id,
                "features": ev.get("features"),
                "prior_daily_baselines": ev.get("prior_daily_baselines"),
            })
        state["daily_entries_count"] = int(
            state.get("daily_entries_count", 0)
        ) + 1
        state["gross_exposure_dollars"] = float(
            state.get("gross_exposure_dollars", 0.0)
        ) + target_notional

        # Persist immediately after the accepted submit + counters so
        # a crash before the end-of-tick write can't lose the pending
        # lot and replay the entry as a duplicate order.
        if state_path is not None:
            try:
                _write_state_atomic(state, state_path)
            except Exception as e:
                LOG.warning(
                    "immediate state persist after submit failed: %s", e,
                )

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
    recorded_exposure: float | None = None,
    prior_daily_baselines: dict | None = None,
    parent_order_style: str = "market",
) -> dict:
    """Write a pending-fill position dict into state['open_positions'].
    Returns the position dict. Called immediately after a successful
    parent submit so poll_fills can match the subsequent fill back to
    the candidate. ``recorded_exposure`` is the notional this entry
    added to ``gross_exposure_dollars`` — the janitor and closure paths
    subtract exactly this amount so the exposure ledger stays symmetric.
    ``prior_daily_baselines`` is stored so the signal-fade pass can
    rebuild the forming-session score intraday.
    """
    now_iso = _iso(_now_utc())
    pos = {
        "symbol": symbol,
        "qty": qty,
        "venue_code": venue_code,
        "parent_order_id": parent_order_id,
        "link_id": link_id,
        # link_id doubles as the broker client_order_id (sent on the
        # parent submit) — the resolver matches unknown-outcome
        # submits back to their lot through this field.
        "client_order_id": link_id,
        "child_order_ids": {"target": "", "stop": ""},
        "status": "pending_fill",
        "recorded_exposure": recorded_exposure,
        "entry_price": None,
        "entry_timestamp": now_iso,
        "parent_submitted_at": now_iso,
        "parent_order_style": parent_order_style,
        "candidate_close": candidate_close,
        "signal_strength": signal_strength,
        "equity_at_entry": equity_at_entry,
        "entry_features": entry_features or {},
        "prior_daily_baselines": prior_daily_baselines or {},
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
    # Keyed by the unique link_id, never by symbol — this is what lets
    # a symbol hold multiple lots, and what makes a re-entry physically
    # unable to overwrite (orphan) an existing lot.
    state.setdefault("open_positions", {})[link_id] = pos
    return pos


def _build_order_index_v2(state: dict) -> dict[str, tuple[str, str]]:
    """Map order_id -> (pos_id, role) for active orders only.

    Mirrors v1's _build_order_index. We only index the parent
    while the position is in a pre-fill state so a duplicate broker
    echo for an already-FILLED parent doesn't re-trigger parent-fill
    handling.
    """
    idx: dict[str, tuple[str, str]] = {}
    for pos_id, pos in (state.get("open_positions") or {}).items():
        if pos.get("status") in {"pending_fill", "submitted", "pending_entry"}:
            pid = pos.get("parent_order_id")
            if pid:
                idx[pid] = (pos_id, "parent")
        for role, oid in (pos.get("child_order_ids") or {}).items():
            if oid:
                idx[oid] = (pos_id, role)
        eid = pos.get("exit_order_id")
        if eid:
            idx[eid] = (pos_id, "exit")
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
    # Strict leg parsing — a stop leg classifies first (covers
    # stop_limit), a plain limit leg is the target. No guessing: a
    # missing or duplicated id means we do NOT know which order is the
    # stop, and storing a wrong id would let trigger_exit cancel the
    # wrong leg later. Treat as attach failure and let the retry
    # sweep / protected-position flatten handle it.
    target_id = ""
    stop_id = ""
    for leg in legs:
        otype = (leg.get("order_type") or leg.get("type") or "").lower()
        leg_id = leg.get("id") or leg.get("order_id") or ""
        if "stop" in otype:
            if not stop_id:
                stop_id = leg_id
        elif "limit" in otype:
            if not target_id:
                target_id = leg_id
    if not target_id or not stop_id or target_id == stop_id:
        _emit_ledger_v2(cfg, "bracket_attach_ambiguous", {
            "symbol": symbol, "link_id": pos.get("link_id"),
            "target_id": target_id, "stop_id": stop_id,
            "legs": legs,
        })
        emit_protection_state(cfg, {
            "ts": _iso(_now_utc()), "symbol": symbol,
            "event": "bracket_attach_ambiguous",
            "target_id": target_id, "stop_id": stop_id,
            "legs": legs,
        })
        LOG.error(
            "OCO attach for %s returned ambiguous legs "
            "(target=%r stop=%r legs=%r) — treating as FAILED",
            symbol, target_id, stop_id, legs,
        )
        return {
            "error": {"code": "bracket_attach_ambiguous"},
            "status": "ambiguous_legs",
        }
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
    for pos_id, pos in list((state.get("open_positions") or {}).items()):
        symbol = pos.get("symbol", "")
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


def _true_up_recorded_exposure(state: dict, pos: dict) -> None:
    """On parent fill, replace the lot's estimated recorded_exposure
    (signal-price notional) with the actual fill notional, adjusting
    gross_exposure_dollars by the delta so entries and closures stay
    symmetric."""
    try:
        entry_price = float(pos.get("entry_price") or 0.0)
        qty = float(pos.get("qty") or 0)
    except (TypeError, ValueError):
        return
    if entry_price <= 0 or qty <= 0:
        return
    new_exposure = entry_price * qty
    old = pos.get("recorded_exposure")
    old_f = (
        float(old)
        if isinstance(old, (int, float)) and not isinstance(old, bool)
        else 0.0
    )
    state["gross_exposure_dollars"] = max(
        0.0,
        float(state.get("gross_exposure_dollars", 0.0))
        + new_exposure - old_f,
    )
    pos["recorded_exposure"] = new_exposure


def _process_order_row(
    row: dict, idx: dict[str, tuple[str, str]],
    state: dict, cfg: dict, events: list[dict],
) -> None:
    """Match one broker order row against the tracked-order index and
    apply the fill / terminal state transitions, appending any
    detected fill event to ``events``. Shared verbatim by the bulk
    ``poll_fills_v2`` pass and the per-id direct-fetch fallback so
    both paths book fills identically. Rows for untracked ids are
    ignored."""
    open_positions = state.setdefault("open_positions", {})
    oid = row.get("id") or row.get("order_id") or ""
    if oid not in idx:
        return
    pos_id, role = idx[oid]
    pos = open_positions.get(pos_id)
    if pos is None:
        return
    symbol = pos.get("symbol", "")
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
        "symbol": symbol, "pos_id": pos_id, "order_id": oid, "role": role,
        "status": canonical, "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_f, "raw": row,
    }
    if role == "parent":
        if (native_status in _FILLED_STATUSES
                or canonical == "FILLED"):
            if pos.get("parent_fill_processed"):
                return
            pos["status"] = "filled"
            pos["entry_price"] = filled_avg_f or pos.get("entry_price")
            if filled_qty > 0:
                pos["qty"] = filled_qty
            pos["parent_fill_processed"] = True
            pos["parent_fill_processed_at"] = _iso(_now_utc())
            _true_up_recorded_exposure(state, pos)
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
                _true_up_recorded_exposure(state, pos)
                events.append(ev)
            else:
                LOG.info(
                    "parent %s ended in %s — dropping position",
                    symbol, canonical,
                )
                open_positions.pop(pos_id, None)
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
        elif ((native_status in _DEAD_STATUSES
               or canonical in {s.upper() for s in _DEAD_STATUSES})
              and filled_qty > 0
              and not (pos.get("child_partial_processed") or {})
                  .get(role)):
            # Child died AFTER a partial execution — real shares
            # traded. Surface the event so process_fill_events_v2
            # books a partial closure (finding 9).
            events.append(ev)
    elif role == "exit":
        if (native_status in _FILLED_STATUSES
                or canonical == "FILLED"):
            pos["exit_fill_price"] = filled_avg_f
            pos["exit_filled_qty"] = filled_qty
            events.append(ev)


def _poll_missing_orders(
    state: dict, cfg: dict, *,
    idx: dict[str, tuple[str, str]], seen: set[str],
    events: list[dict],
    oa_client, api_key: str, http,
    max_direct_fetches: int = 5,
) -> None:
    """Per-id fallback for tracked orders absent from the bulk order
    list (e.g. pushed past the broker's pagination window). A tracked
    id missing from two consecutive bulk polls is fetched directly
    via ``fetch_order`` (round-robin, at most ``max_direct_fetches``
    per tick) and fed through the same row-processing path as bulk
    rows. Miss counters live in ``state['order_poll_misses']`` and
    are dropped for ids that reappear or stop being tracked."""
    misses: dict = state.setdefault("order_poll_misses", {})
    tracked = set(idx)
    for oid in [o for o in misses if o not in tracked]:
        misses.pop(oid, None)
    for oid in tracked:
        if oid in seen:
            misses.pop(oid, None)
        else:
            misses[oid] = int(misses.get(oid, 0) or 0) + 1
    eligible = sorted(o for o, n in misses.items() if int(n or 0) >= 2)
    warned: dict = state.setdefault("order_poll_warned", {})
    for oid in [o for o in warned if o not in tracked]:
        warned.pop(oid, None)
    if not eligible:
        return
    fetch_order = getattr(oa_client, "fetch_order", None)
    if not callable(fetch_order):
        return
    cursor = int(state.get("order_poll_fetch_cursor", 0) or 0)
    n = min(int(max_direct_fetches), len(eligible))
    batch = [eligible[(cursor + i) % len(eligible)] for i in range(n)]
    state["order_poll_fetch_cursor"] = (cursor + n) % len(eligible)
    today = _today_iso()
    for oid in batch:
        try:
            row = fetch_order(http, api_key, oid)
        except Exception as e:
            LOG.warning("direct order fetch raised for %s: %s", oid, e)
            row = None
        usable = (
            isinstance(row, dict)
            and row.get("_status") != "not_found"
            and (row.get("id") or row.get("order_id"))
        )
        if not usable:
            # Leave the miss counter — retried on a later tick.
            if warned.get(oid) != today:
                warned[oid] = today
                LOG.warning(
                    "tracked order %s missing from bulk order list "
                    "(%s misses); direct fetch returned %s — will retry",
                    oid, misses.get(oid),
                    "not_found" if isinstance(row, dict) else "no data",
                )
            continue
        misses.pop(oid, None)
        _process_order_row(row, idx, state, cfg, events)


def poll_fills_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[dict]:
    """GET /api/v2/orders?status=all and reconcile fills against state.
    Updates state in place. Returns the list of detected fill events
    (each: ``{symbol, order_id, role, status, filled_qty,
    filled_avg_price}``). Tracked ids absent from the bulk response
    for 2+ consecutive polls are fetched per-id via
    ``_poll_missing_orders`` so a fill can never be silently lost to
    the broker's list window."""
    if not state.get("open_positions"):
        return []
    try:
        rows = oa_client.fetch_all_orders(http, api_key)
    except Exception as e:
        LOG.warning("poll_fills_v2 fetch failed: %s", e)
        return []
    idx = _build_order_index_v2(state)
    events: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        oid = row.get("id") or row.get("order_id") or ""
        if oid:
            seen.add(oid)
        _process_order_row(row, idx, state, cfg, events)
    try:
        _poll_missing_orders(
            state, cfg, idx=idx, seen=seen, events=events,
            oa_client=oa_client, api_key=api_key, http=http,
        )
    except Exception:
        LOG.exception("_poll_missing_orders raised")
    return events


#: Resolver passes after which a client_order_id absent from the
#: broker's order list is declared never-placed and its lot dropped.
_RESOLVER_MAX_MISSES = 12


def resolve_unknown_submits(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """Adjudicate lots recorded with ``outcome_unresolved`` (submit
    raised, or was accepted with no order id). Scans the broker's
    order list for each lot's ``client_order_id``:

    - found → the order DID reach the broker: adopt its order id,
      clear the flag (ledger ``unknown_submit_resolved_present``);
      the normal poll path takes over from there.
    - absent for ``_RESOLVER_MAX_MISSES`` consecutive passes → the
      order never landed: drop the lot and restore its reserved
      exposure (ledger ``unknown_submit_resolved_absent``).

    While any lot is unresolved, ``_risk_gates`` blocks all new
    entries (``unresolved_order_outcome``) and the pending-fill
    janitor skips these lots (this resolver owns them). Runs each
    tick BEFORE the janitor. Returns the pos_ids resolved (either
    way) this pass."""
    lots = [
        (pid, pos)
        for pid, pos in (state.get("open_positions") or {}).items()
        if pos.get("outcome_unresolved")
    ]
    if not lots:
        return []
    try:
        rows = oa_client.fetch_all_orders(http, api_key)
    except Exception as e:
        LOG.warning("resolver orders fetch failed: %s", e)
        return []
    by_coid: dict[str, dict] = {}
    for row in rows or []:
        coid = row.get("client_order_id")
        if coid:
            by_coid[str(coid)] = row
    out: list[str] = []
    for pid, pos in lots:
        symbol = pos.get("symbol", "")
        coid = str(pos.get("client_order_id") or pos.get("link_id") or "")
        row = by_coid.get(coid)
        if row is not None:
            oid = str(row.get("id") or row.get("order_id") or "")
            pos["parent_order_id"] = oid
            pos.pop("outcome_unresolved", None)
            pos.pop("resolver_misses", None)
            _emit_ledger_v2(cfg, "unknown_submit_resolved_present", {
                "symbol": symbol, "link_id": pos.get("link_id"),
                "client_order_id": coid, "parent_order_id": oid,
            })
            LOG.warning(
                "unknown submit for %s RESOLVED: order %s exists at "
                "broker (client_order_id=%s) — lot adopted",
                symbol, oid, coid,
            )
            out.append(pid)
            continue
        misses = int(pos.get("resolver_misses", 0) or 0) + 1
        pos["resolver_misses"] = misses
        if misses < _RESOLVER_MAX_MISSES:
            continue
        exposure = pos.get("recorded_exposure")
        if not isinstance(exposure, (int, float)) or isinstance(
            exposure, bool,
        ):
            exposure = 0.0
        state["gross_exposure_dollars"] = max(
            0.0,
            float(state.get("gross_exposure_dollars", 0.0))
            - float(exposure),
        )
        state["open_positions"].pop(pid, None)
        _emit_ledger_v2(cfg, "unknown_submit_resolved_absent", {
            "symbol": symbol, "link_id": pos.get("link_id"),
            "client_order_id": coid, "resolver_misses": misses,
            "restored_exposure": float(exposure),
        })
        LOG.warning(
            "unknown submit for %s RESOLVED: client_order_id %s absent "
            "from broker after %d passes — never placed; lot dropped",
            symbol, coid, misses,
        )
        out.append(pid)
    return out


def expire_stale_pending_fills(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
    now_utc: datetime | None = None,
) -> list[str]:
    """Janitor for lots stuck in ``pending_fill``: after
    ``execution.pending_fill_timeout_seconds`` (default 900) with no
    fill echo, cancel the parent order and — once the cancel is
    VERIFIED terminal with zero fill — drop the lot and restore the
    exposure it reserved. A cancel that raced a fill ADOPTS the lot
    as filled instead (the shares are real; the OCO sweep brackets it
    the same tick). A cancel whose outcome cannot be confirmed leaves
    the lot for the next tick — a lot whose parent state is unknown
    is NEVER dropped. Runs each loop tick after ``poll_fills_v2``, so
    a fill echo that arrives first wins. Marketable-limit parents use
    the (much shorter) ``execution.marketable_limit_timeout_seconds``.
    Returns the symbols expired (dropped) this pass."""
    exec_cfg = cfg.get("execution") or {}
    default_timeout_s = float(exec_cfg.get(
        "pending_fill_timeout_seconds", 900,
    ))
    ml_timeout_s = float(exec_cfg.get(
        "marketable_limit_timeout_seconds", 30,
    ))
    now = now_utc or _now_utc()
    out: list[str] = []
    open_positions = state.get("open_positions") or {}
    for pos_id, pos in list(open_positions.items()):
        if pos.get("status") != "pending_fill":
            continue
        # Unknown-outcome lots belong to resolve_unknown_submits —
        # they have no parent id to cancel and must not be dropped
        # on a timeout.
        if pos.get("outcome_unresolved"):
            continue
        timeout_s = (
            ml_timeout_s
            if pos.get("parent_order_style") == "marketable_limit"
            else default_timeout_s
        )
        entry_iso = pos.get("entry_timestamp")
        try:
            ts = pd.Timestamp(entry_iso)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            age_s = (pd.Timestamp(now) - ts).total_seconds()
        except Exception:
            continue
        if age_s <= timeout_s:
            continue
        symbol = pos.get("symbol", "")
        parent_id = pos.get("parent_order_id") or ""
        verdict = "canceled"  # no parent id ⇒ nothing at the broker
        row: dict | None = None
        if parent_id:
            try:
                res = oa_client.cancel_order(http, api_key, parent_id)
            except Exception as e:
                LOG.exception(
                    "janitor cancel of stale parent %s (%s) failed",
                    parent_id, symbol,
                )
                res = {"status": "error", "order_id": parent_id,
                       "exception": str(e)}
            status = res.get("status") if isinstance(res, dict) else None
            if status in ("canceled", "noop"):
                verdict, row = _await_cancel_terminal(
                    oa_client, http, api_key, parent_id,
                    treat_not_found_as_canceled=True,
                )
            else:
                # Cancel errored — probe the parent once. Unknown
                # state must never drop the lot.
                verdict, row = _probe_order_state(
                    oa_client, http, api_key, parent_id,
                )
        if verdict == "filled":
            # The cancel raced the parent's fill: real shares were
            # bought. Adopt the lot as filled so the OCO sweep
            # brackets it this same tick; never drop it.
            fq = _row_filled_qty(row)
            try:
                fap = float((row or {}).get("filled_avg_price"))
            except (TypeError, ValueError):
                fap = None
            pos["status"] = "filled"
            if fap and fap > 0:
                pos["entry_price"] = fap
            if fq > 0:
                pos["qty"] = fq
            pos["parent_fill_processed"] = True
            pos["parent_fill_processed_at"] = _iso(_now_utc())
            _true_up_recorded_exposure(state, pos)
            ep = pos.get("entry_price")
            if ep is not None and pos.get("peak_since_entry") is None:
                pos["peak_since_entry"] = float(ep)
                pos["trough_since_entry"] = float(ep)
            _emit_ledger_v2(cfg, "janitor_cancel_raced_fill", {
                "symbol": symbol, "link_id": pos.get("link_id"),
                "parent_order_id": parent_id,
                "filled_qty": fq, "filled_avg_price": fap,
                "age_seconds": age_s,
            })
            LOG.warning(
                "janitor cancel of %s parent %s raced a FILL — lot "
                "adopted (qty=%s @ %s); OCO sweep will bracket it",
                symbol, parent_id, fq, fap,
            )
            continue
        if verdict == "pending":
            LOG.warning(
                "janitor: parent %s (%s) cancel outcome unconfirmed — "
                "lot retained for retry next tick", parent_id, symbol,
            )
            continue
        # verdict == "canceled": confirmed dead with zero fill.
        exposure = pos.get("recorded_exposure")
        if not isinstance(exposure, (int, float)) or isinstance(
            exposure, bool,
        ):
            exposure = 0.0
        state["gross_exposure_dollars"] = max(
            0.0,
            float(state.get("gross_exposure_dollars", 0.0))
            - float(exposure),
        )
        open_positions.pop(pos_id, None)
        _emit_ledger_v2(cfg, "pending_fill_expired", {
            "symbol": symbol, "link_id": pos.get("link_id"),
            "parent_order_id": parent_id,
            "age_seconds": age_s, "timeout_seconds": timeout_s,
            "restored_exposure": float(exposure),
        })
        LOG.warning(
            "pending fill for %s expired after %.0fs (timeout %.0fs) — "
            "parent %s canceled, lot dropped", symbol, age_s, timeout_s,
            parent_id or "<none>",
        )
        out.append(symbol)
    return out


def _probe_order_state(
    oa_client, http, api_key: str, order_id: str,
) -> tuple[str, dict | None]:
    """Single status probe for an order whose cancel ERRORED. Maps to
    the same verdict vocabulary as :func:`_await_cancel_terminal`:
    filled/partial ⇒ ``"filled"``; confirmed dead with zero fill ⇒
    ``"canceled"``; still live, not_found, or probe failure ⇒
    ``"pending"`` (unknown — the caller must retain the lot)."""
    fetch_order = getattr(oa_client, "fetch_order", None)
    if not callable(fetch_order):
        return "pending", None
    try:
        row = fetch_order(http, api_key, order_id)
    except Exception as e:
        LOG.warning("order-state probe raised for %s: %s", order_id, e)
        return "pending", None
    if not isinstance(row, dict) or row.get("_status") == "not_found":
        return "pending", row if isinstance(row, dict) else None
    status = str(
        row.get("native_status") or row.get("status") or "",
    ).lower()
    filled_qty = _row_filled_qty(row)
    if status == "filled" or filled_qty > 0:
        return "filled", row
    if status in _DEAD_STATUSES_LOWER:
        return "canceled", row
    return "pending", row


def recover_stuck_exit_pending(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
    now_utc: datetime | None = None,
    max_age_s: float = 120.0,
) -> list[str]:
    """Recovery sweep for lots stranded in ``exit_pending`` — the
    reserve state trigger_exit_v2 sets before its cancel/sell I/O. A
    crash inside that window leaves the lot frozen forever: no exit
    pass touches non-'filled' lots and nothing re-enters
    ``exit_pending``. Any such lot older than ``max_age_s`` (or
    missing its ``exit_pending_at`` stamp entirely ⇒ stale) is
    reverted to ``filled``:

    - If ANY recorded child is still live (or its state is unknown),
      the bracket is kept intact — child ids untouched. The next
      management pass re-drives the exit.
    - If every recorded child is confirmed dead with zero fill (or
      absent at the broker), the ids are cleared so
      submit_pending_oco_children_v2 re-attaches a fresh bracket.
    - A dead child WITH fills keeps its id — the fill echo books the
      closure through the normal poll path.

    Emits protection event ``exit_pending_recovered``. Returns the
    recovered pos_ids. Runs at startup (after reconcile) and every
    loop tick between poll_fills_v2 and the OCO sweep."""
    now = now_utc or _now_utc()
    out: list[str] = []
    fetch_order = getattr(oa_client, "fetch_order", None)
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") != "exit_pending":
            continue
        stamp = pos.get("exit_pending_at")
        if stamp:
            try:
                ts = pd.Timestamp(stamp)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                age_s = (pd.Timestamp(now) - ts).total_seconds()
                if age_s <= float(max_age_s):
                    continue
            except Exception:
                pass  # unparseable stamp ⇒ stale
        symbol = pos.get("symbol", "")
        children = dict(pos.get("child_order_ids") or {})
        dead_roles: list[str] = []
        live_or_unknown: list[str] = []
        for role, oid in children.items():
            if not oid:
                continue
            row = None
            if callable(fetch_order):
                try:
                    row = fetch_order(http, api_key, oid)
                except Exception as e:
                    LOG.warning(
                        "exit_pending recovery: child fetch raised for "
                        "%s: %s", oid, e,
                    )
                    row = None
            if isinstance(row, dict) and row.get("_status") == "not_found":
                dead_roles.append(role)
                continue
            if isinstance(row, dict):
                status_l = str(
                    row.get("native_status") or row.get("status") or "",
                ).lower()
                if (status_l in _DEAD_STATUSES_LOWER
                        and _row_filled_qty(row) == 0):
                    dead_roles.append(role)
                    continue
            live_or_unknown.append(role)
        cleared: list[str] = []
        if dead_roles and not live_or_unknown:
            # Every recorded child confirmed dead/absent — clear so
            # the OCO sweep re-attaches. (Never clear a subset: a
            # fresh full-qty bracket next to a live old leg could
            # oversell.)
            for role in dead_roles:
                pos["child_order_ids"][role] = ""
            cleared = dead_roles
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        emit_protection_state(cfg, {
            "ts": _iso(now), "symbol": symbol,
            "event": "exit_pending_recovered",
            "link_id": pos.get("link_id"),
            "cleared_children": cleared,
            "kept_children": live_or_unknown,
        })
        _emit_ledger_v2(cfg, "exit_pending_recovered", {
            "symbol": symbol, "link_id": pos.get("link_id"),
            "cleared_children": cleared,
            "kept_children": live_or_unknown,
        })
        LOG.warning(
            "recovered %s from stranded exit_pending (cleared=%s "
            "kept=%s) — lot reverted to filled", symbol, cleared,
            live_or_unknown,
        )
        out.append(pos_id)
    return out


def _broker_position_rows(rows: list[dict]) -> dict[str, float]:
    """Normalize /api/v2/positions rows into {symbol: qty}, dropping
    flat rows. Field names parsed defensively across payload shapes."""
    out: dict[str, float] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = (
            row.get("symbol")
            or row.get("canonical_symbol")
            or (row.get("instrument") or {}).get("canonical_symbol")
            or ""
        )
        if not sym:
            continue
        qty_raw = row.get("qty")
        if qty_raw is None:
            qty_raw = row.get("quantity")
        if qty_raw is None:
            qty_raw = row.get("net_quantity")
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            continue
        if qty != 0:
            out[str(sym)] = out.get(str(sym), 0.0) + qty
    return out


def reconcile_with_broker(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
    state_parse_failed: bool = False,
) -> int | None:
    """Startup broker-truth reconciliation. Compares broker positions
    against state['open_positions'].

    - Broker position with no state lot (orphan): ERROR + protection
      event ``orphan_position_detected``; when
      ``reconcile.halt_on_orphans`` (default true) return exit code 7
      so the process refuses to trade blind.
    - State lot with no broker position: mark
      ``pos['broker_missing']`` and WARN (likely closed while down;
      the order echo on the next poll resolves it — never auto-drop).
    - When the state file failed to parse entirely AND the broker
      holds positions: always return 7 regardless of the flag.

    Returns an exit code to abort with, or None to continue.
    """
    try:
        broker_rows = oa_client.fetch_positions(http, api_key)
    except Exception as e:
        LOG.warning(
            "broker reconciliation skipped: positions fetch failed (%s)",
            e,
        )
        return None
    try:
        order_count = len(oa_client.fetch_all_orders(http, api_key))
    except Exception:
        order_count = None
    broker_pos = _broker_position_rows(broker_rows)
    state_symbols: dict[str, list[dict]] = {}
    for pos in (state.get("open_positions") or {}).values():
        state_symbols.setdefault(pos.get("symbol", ""), []).append(pos)
    LOG.info(
        "broker reconciliation: broker holds %d symbol(s), state holds "
        "%d lot(s)%s", len(broker_pos),
        len(state.get("open_positions") or {}),
        f", {order_count} order rows" if order_count is not None else "",
    )

    if state_parse_failed and broker_pos:
        LOG.error(
            "state.json was unrecoverable and the broker reports %d open "
            "position(s) (%s) — refusing to trade blind (exit 7)",
            len(broker_pos), sorted(broker_pos),
        )
        return 7

    orphans = [s for s in broker_pos if s not in state_symbols]
    for sym in orphans:
        LOG.error(
            "orphan broker position: %s qty=%s has no state lot",
            sym, broker_pos[sym],
        )
        emit_protection_state(cfg, {
            "ts": _iso(_now_utc()), "symbol": sym,
            "event": "orphan_position_detected",
            "broker_qty": broker_pos[sym],
        })
    for sym, lots in state_symbols.items():
        if sym and sym not in broker_pos:
            for pos in lots:
                if pos.get("status") in {"pending_fill", "submitted",
                                          "pending_entry"}:
                    continue  # not expected at the broker yet
                pos["broker_missing"] = True
                LOG.warning(
                    "state lot %s (%s) not present at broker — marked "
                    "broker_missing; awaiting order echo",
                    pos.get("link_id"), sym,
                )
    # Qty comparison for symbols present on BOTH sides — a missed
    # partial fill or a lost echo leaves the state qty out of step
    # with the broker's. Warn + protection event only; never halt
    # (the order echoes and the janitor resolve the drift).
    for sym, lots in state_symbols.items():
        if not sym or sym not in broker_pos:
            continue
        state_qty = 0.0
        for pos in lots:
            if pos.get("status") not in {"filled", "exiting",
                                          "exit_pending"}:
                continue
            try:
                state_qty += float(pos.get("qty") or 0)
            except (TypeError, ValueError):
                pass
        broker_qty = float(broker_pos[sym])
        if abs(state_qty - broker_qty) > 1e-9:
            LOG.warning(
                "qty mismatch for %s: state holds %.4f, broker holds "
                "%.4f", sym, state_qty, broker_qty,
            )
            emit_protection_state(cfg, {
                "ts": _iso(_now_utc()), "symbol": sym,
                "event": "qty_mismatch",
                "state_qty": state_qty, "broker_qty": broker_qty,
            })
    if orphans:
        halt = bool((cfg.get("reconcile") or {}).get(
            "halt_on_orphans", True,
        ))
        if halt:
            LOG.error(
                "reconcile.halt_on_orphans=true and %d orphan(s) found — "
                "exit 7 (watchdog will NOT restart)", len(orphans),
            )
            return 7
        LOG.warning(
            "continuing despite %d orphan position(s) "
            "(reconcile.halt_on_orphans=false)", len(orphans),
        )
    return None


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
    pos_id: str,
    state: dict,
    cfg: dict,
    *,
    exit_price: float,
    reason: str,
) -> dict | None:
    """Compute realized PnL, append a closure record to the v2 daily
    summary + ledger, then drop the lot from state. ``pos_id`` is the
    link_id-keyed open_positions key — one lot, not the whole symbol."""
    pos = (state.get("open_positions") or {}).get(pos_id)
    if pos is None:
        return None
    symbol = pos.get("symbol", "")
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
    # Stop-out circuit-breaker counters (v1 parity): any stop_hit
    # bumps both counters and starts the post-stopout cooldown; any
    # non-stop closure resets the consecutive streak.
    if reason == "stop_hit":
        state["daily_stopout_count"] = int(
            state.get("daily_stopout_count", 0) or 0,
        ) + 1
        state["consecutive_stopout_count"] = int(
            state.get("consecutive_stopout_count", 0) or 0,
        ) + 1
        cooldown_min = (cfg.get("scanner") or {}).get(
            "symbol_cooldown_minutes",
        )
        if cooldown_min:
            until = _now_utc() + timedelta(minutes=float(cooldown_min))
            state.setdefault("cooldowns", {})[symbol] = {
                "until": _iso(until), "reason": "stop_hit",
            }
    else:
        state["consecutive_stopout_count"] = 0
    # Update strategy-tracked PnL + gross exposure.
    state["daily_realized_pnl_strategy"] = float(
        state.get("daily_realized_pnl_strategy", 0.0)
    ) + realized
    # Lifetime realized PnL — drives the compounding sizing bankroll.
    # Kept in sync in-memory here; reconciled authoritatively from the
    # closure ledger on load (main()), which heals any crash-window gap
    # before the next state write. NOT reset on daily session rollover.
    state["cumulative_realized_pnl_strategy"] = float(
        state.get("cumulative_realized_pnl_strategy", 0.0)
    ) + realized
    # Subtract exactly what the entry added (recorded_exposure, trued
    # up on fill); legacy lots without it fall back to fill notional.
    exposure = pos.get("recorded_exposure")
    if (not isinstance(exposure, (int, float))
            or isinstance(exposure, bool) or exposure <= 0):
        exposure = entry_price * qty
    state["gross_exposure_dollars"] = max(
        0.0,
        float(state.get("gross_exposure_dollars", 0.0)) - float(exposure),
    )
    state["open_positions"].pop(pos_id, None)
    LOG.info(
        "closed %s: %s pnl=%.2f hold_td=%s entry=%.4f exit=%.4f",
        symbol, reason, realized, hold_trading_days,
        entry_price, float(exit_price),
    )
    return record


def close_position_partial_v2(
    pos_id: str,
    state: dict,
    cfg: dict,
    *,
    exit_price: float,
    reason: str,
    qty_filled: int,
) -> dict | None:
    """Book a PARTIAL closure for ``qty_filled`` shares of a lot whose
    OCO child died after a partial execution: writes a closure record
    for exactly that qty (reasons ``target_hit_partial`` /
    ``stop_hit_partial``), updates daily + cumulative realized PnL,
    and reduces the lot's qty / recorded_exposure / gross exposure
    proportionally. The lot is NOT popped — the caller clears the
    dead OCO pair's ids and reverts status to ``filled`` so the sweep
    re-brackets the remaining shares.

    Stop-out circuit-breaker counters deliberately do NOT bump here:
    they count FULL stop closes only (``close_position_v2`` with
    reason ``stop_hit``). A partially-stopped remainder stays managed
    under a fresh bracket rather than counting as a completed
    stop-out."""
    pos = (state.get("open_positions") or {}).get(pos_id)
    if pos is None:
        return None
    qty_filled = int(qty_filled)
    total_qty = int(pos.get("qty") or 0)
    if qty_filled <= 0 or total_qty <= 0:
        return None
    qty_filled = min(qty_filled, total_qty)
    symbol = pos.get("symbol", "")
    entry_price = float(pos.get("entry_price") or 0.0)
    realized = (float(exit_price) - entry_price) * qty_filled
    record = {
        "record_type": "closure",
        "symbol": symbol,
        "qty": qty_filled,
        "entry_price": entry_price,
        "exit_price": float(exit_price),
        "entry_timestamp": pos.get("entry_timestamp"),
        "exit_timestamp": _iso(_now_utc()),
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
        "entry_trigger": pos.get("entry_trigger"),
        "partial": True,
        "remaining_qty": total_qty - qty_filled,
    }
    _append_closure_summary(cfg, record)
    _emit_ledger_v2(cfg, "closure", record)
    state["daily_realized_pnl_strategy"] = float(
        state.get("daily_realized_pnl_strategy", 0.0)
    ) + realized
    state["cumulative_realized_pnl_strategy"] = float(
        state.get("cumulative_realized_pnl_strategy", 0.0)
    ) + realized
    # Proportional exposure release for the closed slice.
    exposure = pos.get("recorded_exposure")
    if (not isinstance(exposure, (int, float))
            or isinstance(exposure, bool) or exposure <= 0):
        exposure = entry_price * total_qty
    frac = qty_filled / float(total_qty)
    delta = float(exposure) * frac
    pos["recorded_exposure"] = max(0.0, float(exposure) - delta)
    state["gross_exposure_dollars"] = max(
        0.0,
        float(state.get("gross_exposure_dollars", 0.0)) - delta,
    )
    pos["qty"] = total_qty - qty_filled
    LOG.warning(
        "partial closure for %s: %d of %d @ %.4f (%s) pnl=%.2f — "
        "%d shares remain", symbol, qty_filled, total_qty,
        float(exit_price), reason, realized, total_qty - qty_filled,
    )
    return record


def _positive_price(v) -> float | None:
    """float(v) when it is a usable positive price, else None."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _resolve_exit_price(ev: dict, pos: dict, role: str) -> float | None:
    """Best usable exit price for a fill event: the broker's
    filled_avg_price, then the role-appropriate stored price. None
    when no positive price is available — the caller must defer the
    closure rather than book a 0.0 exit (−100% phantom PnL)."""
    if role == "target":
        chain = (ev.get("filled_avg_price"), pos.get("target_price"))
    elif role == "stop":
        chain = (ev.get("filled_avg_price"), pos.get("stop_price"))
    else:  # exit (market sell)
        chain = (ev.get("filled_avg_price"), pos.get("exit_fill_price"))
    for candidate in chain:
        price = _positive_price(candidate)
        if price is not None:
            return price
    return None


def _defer_closure_no_price(cfg: dict, pos: dict, ev: dict) -> None:
    """Mark the lot as awaiting a usable exit price; the next poll's
    broker echo should carry filled_avg_price. Ledger event emitted
    once per lot."""
    pos["exit_price_pending"] = True
    if not pos.get("closure_deferred_logged"):
        pos["closure_deferred_logged"] = True
        _emit_ledger_v2(cfg, "closure_deferred_no_price", {
            "symbol": pos.get("symbol"), "link_id": pos.get("link_id"),
            "role": ev.get("role"), "order_id": ev.get("order_id"),
        })
    LOG.warning(
        "no usable exit price for %s (%s fill, order %s) — closure "
        "deferred until the broker echo carries filled_avg_price",
        pos.get("symbol"), ev.get("role"), ev.get("order_id"),
    )


def process_fill_events_v2(
    events: list[dict], state: dict, cfg: dict,
) -> list[dict]:
    """Map child/exit fill events to closures. A fill with no usable
    price defers the closure (never books exit_price=0.0). A DEAD
    target/stop child with a partial fill books a partial closure for
    the executed shares and re-brackets the remainder."""
    dead_upper = {s.upper() for s in _DEAD_STATUSES}
    out: list[dict] = []
    open_positions = state.get("open_positions") or {}
    for ev in events:
        pos_id = ev["pos_id"]
        pos = open_positions.get(pos_id)
        if pos is None:
            continue
        role = ev["role"]
        if (role in ("target", "stop") and ev["status"] in dead_upper
                and int(ev.get("filled_qty") or 0) > 0):
            # OCO child died after a partial execution (finding 9).
            processed = pos.setdefault("child_partial_processed", {})
            if processed.get(role):
                continue
            price = _resolve_exit_price(ev, pos, role)
            if price is None:
                _defer_closure_no_price(cfg, pos, ev)
                continue
            base_reason = "target_hit" if role == "target" else "stop_hit"
            filled_qty = int(ev.get("filled_qty") or 0)
            remaining = int(pos.get("qty") or 0) - filled_qty
            if remaining <= 0:
                # The "partial" covered the whole lot — full closure
                # (stop-out counters DO bump for a full stop here).
                rec = close_position_v2(
                    pos_id, state, cfg,
                    exit_price=price, reason=base_reason,
                )
                if rec:
                    out.append(rec)
                continue
            rec = close_position_partial_v2(
                pos_id, state, cfg,
                exit_price=price, reason=f"{base_reason}_partial",
                qty_filled=filled_qty,
            )
            if rec:
                processed[role] = True
                # The OCO pair dies together at Alpaca — clear BOTH
                # ids and revert to filled so the sweep re-attaches a
                # fresh bracket sized to the remaining shares.
                pos["child_order_ids"] = {"target": "", "stop": ""}
                pos["status"] = "filled"
                out.append(rec)
            continue
        if role == "target" and ev["status"] in {"FILLED"}:
            price = _resolve_exit_price(ev, pos, "target")
            if price is None:
                _defer_closure_no_price(cfg, pos, ev)
                continue
            rec = close_position_v2(
                pos_id, state, cfg,
                exit_price=price, reason="target_hit",
            )
            if rec:
                out.append(rec)
        elif role == "stop" and ev["status"] in {"FILLED"}:
            price = _resolve_exit_price(ev, pos, "stop")
            if price is None:
                _defer_closure_no_price(cfg, pos, ev)
                continue
            rec = close_position_v2(
                pos_id, state, cfg,
                exit_price=price, reason="stop_hit",
            )
            if rec:
                out.append(rec)
        elif role == "exit" and ev["status"] in {"FILLED"}:
            price = _resolve_exit_price(ev, pos, "exit")
            if price is None:
                _defer_closure_no_price(cfg, pos, ev)
                continue
            exit_reason = pos.get("exit_reason") or "time_stop"
            rec = close_position_v2(
                pos_id, state, cfg,
                exit_price=price, reason=exit_reason,
            )
            if rec:
                out.append(rec)
    return out


# Cancel-verification polling knobs. Tests monkeypatch these to
# (small, 0.0) so verify-timeout paths don't sleep for real.
_CANCEL_VERIFY_ATTEMPTS = 6
_CANCEL_VERIFY_SLEEP_S = 0.5

_DEAD_STATUSES_LOWER = frozenset(s.lower() for s in _DEAD_STATUSES)


def _row_filled_qty(row: dict | None) -> int:
    try:
        return int(float(
            (row or {}).get("filled_qty")
            or (row or {}).get("filled_quantity") or 0,
        ))
    except (TypeError, ValueError):
        return 0


def _await_cancel_terminal(
    oa_client, http, api_key: str, order_id: str, *,
    attempts: int | None = None, sleep_s: float | None = None,
    treat_not_found_as_canceled: bool = False,
) -> tuple[str, dict | None]:
    """Poll an order after a cancel request until it reaches a
    terminal state. OpenAlgo wraps Alpaca's ASYNC cancel — a
    cancel-accept only means ``pending_cancel``; the order can still
    fill. Returns ``(verdict, row)`` where verdict is:

    - ``"canceled"``: terminal dead status with zero filled qty.
    - ``"filled"``: FILLED, or ANY terminal status with
      filled_qty > 0 (a partial fill on a canceled order traded real
      shares and must be booked by the caller).
    - ``"pending"``: still live / pending_cancel after ``attempts``
      polls, or the status fetch kept failing — the caller must NOT
      assume the cancel took.

    ``treat_not_found_as_canceled`` must be True only when the caller
    has just received a cancel-accept for this exact id. An oa_client
    without ``fetch_order`` (legacy test surrogates) is trusted at
    its cancel-accept word — verdict ``"canceled"`` — because the
    live client always ships ``fetch_order``.
    """
    if attempts is None:
        attempts = _CANCEL_VERIFY_ATTEMPTS
    if sleep_s is None:
        sleep_s = _CANCEL_VERIFY_SLEEP_S
    fetch_order = getattr(oa_client, "fetch_order", None)
    if not callable(fetch_order):
        return "canceled", None
    row: dict | None = None
    for attempt in range(max(1, int(attempts))):
        if attempt:
            time.sleep(max(0.0, float(sleep_s)))
        try:
            row = fetch_order(http, api_key, order_id)
        except Exception as e:
            LOG.warning(
                "cancel-verify fetch raised for %s: %s", order_id, e,
            )
            row = None
        if not isinstance(row, dict):
            continue
        if row.get("_status") == "not_found":
            if treat_not_found_as_canceled:
                return "canceled", None
            continue
        status = str(
            row.get("native_status") or row.get("status") or "",
        ).lower()
        filled_qty = _row_filled_qty(row)
        if status == "filled" or (
            status in _DEAD_STATUSES_LOWER and filled_qty > 0
        ):
            return "filled", row
        if status in _DEAD_STATUSES_LOWER:
            return "canceled", row
        # live / pending_cancel / partially_filled → keep polling.
    return "pending", row


def trigger_exit_v2(
    symbol: str,
    pos: dict,
    cfg: dict,
    *,
    oa_client, api_key: str, http,
    reason: str = "time_stop",
    time_in_force: str = "DAY",
    order_style: str = "market",
    limit_price: float | None = None,
) -> bool:
    """Cancel any OCO children and submit a SELL exit. Default style
    is a MARKET sell; ``order_style="marketable_limit"`` with a
    positive ``limit_price`` submits a LIMIT sell at that price
    (signal-fade exits), falling back to market when no usable price
    was supplied. Returns True iff the broker accepted the exit.
    Idempotent: no-op when status != 'filled'."""
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

    def _revert_to_filled() -> None:
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)

    # Every existing child must be CONFIRMED canceled before the
    # market sell goes out — a still-live stop/target plus a market
    # sell would leave the account short after both fill. The cancel
    # accept alone is not confirmation (async at the broker); each
    # accepted cancel is verified terminal via _await_cancel_terminal.
    # Any failure aborts the exit; the next tick retries.
    children = pos.get("child_order_ids") or {}
    for role in ("target", "stop"):
        oid = children.get(role)
        if not oid:
            continue
        try:
            res = oa_client.cancel_order(http, api_key, oid)
        except Exception as e:
            LOG.error("cancel %s child %s raised: %s", symbol, role, e)
            res = {"status": "error", "order_id": oid,
                   "exception": str(e)}
        status = res.get("status") if isinstance(res, dict) else None
        if status not in ("canceled", "noop"):
            _revert_to_filled()
            _emit_ledger_v2(cfg, "exit_aborted_cancel_failed", {
                "symbol": symbol, "link_id": pos.get("link_id"),
                "role": role, "order_id": oid, "reason": reason,
                "cancel_response": res,
            })
            LOG.error(
                "exit for %s aborted: cancel of %s child %s not "
                "confirmed (%r) — will retry next tick",
                symbol, role, oid, res,
            )
            return False
        if status == "canceled":
            verdict, _row = _await_cancel_terminal(
                oa_client, http, api_key, oid,
                treat_not_found_as_canceled=True,
            )
            if verdict == "filled":
                # The cancel raced the child's own fill — the position
                # already exited at the broker. Selling now would go
                # short. Revert; the fill echo books the closure.
                _revert_to_filled()
                _emit_ledger_v2(cfg, "exit_aborted_child_filled", {
                    "symbol": symbol, "link_id": pos.get("link_id"),
                    "role": role, "order_id": oid, "reason": reason,
                })
                LOG.warning(
                    "exit for %s aborted: %s child %s FILLED during "
                    "cancel — fill echo will book the closure; no "
                    "market sell", symbol, role, oid,
                )
                return False
            if verdict == "pending":
                _revert_to_filled()
                _emit_ledger_v2(cfg, "exit_aborted_cancel_unconfirmed", {
                    "symbol": symbol, "link_id": pos.get("link_id"),
                    "role": role, "order_id": oid, "reason": reason,
                })
                LOG.error(
                    "exit for %s aborted: cancel of %s child %s never "
                    "went terminal — will retry next tick",
                    symbol, role, oid,
                )
                return False
    venue = pos.get("venue_code") or (cfg.get("execution") or {}).get(
        "default_venue_code", "XNAS",
    )
    use_limit = (
        order_style == "marketable_limit"
        and limit_price is not None and float(limit_price) > 0
    )
    # Deterministic exit client_order_id: {link_id}-EXIT{n}. n only
    # advances on a CONFIRMED broker rejection — an unknown-outcome
    # submit reuses the same n, so a crash-replayed duplicate is
    # rejected by the broker (duplicate client_order_id) and adopted
    # via _find_order_id_by_coid instead of selling twice.
    attempt = int(pos.get("exit_attempt", 0) or 0)
    exit_coid = f"{pos.get('link_id') or symbol}-EXIT{attempt}"

    def _submit_sell():
        kwargs: dict = dict(
            venue_code=venue, symbol=symbol, qty=int(pos["qty"]),
            time_in_force=time_in_force,
        )
        if use_limit:
            fn = oa_client.submit_limit_sell
            kwargs["price"] = float(limit_price)
        else:
            fn = oa_client.submit_market_sell
        try:
            return fn(http, api_key, client_order_id=exit_coid, **kwargs)
        except TypeError:
            # Legacy client/test surrogate without the kwarg.
            return fn(http, api_key, **kwargs)

    def _adopt_existing_exit() -> bool:
        """A sell with this client_order_id may already be live at the
        broker (crash replay / raced submit). Adopt it instead of
        submitting another sell."""
        existing = _find_order_id_by_coid(
            oa_client, http, api_key, exit_coid,
        )
        if not existing:
            return False
        pos["status"] = "exiting"
        pos["exit_reason"] = reason
        pos["exit_order_id"] = existing
        pos["exit_submitted_at"] = _iso(_now_utc())
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        _emit_ledger_v2(cfg, "exit_adopted_existing", {
            "symbol": symbol, "exit_order_id": existing,
            "client_order_id": exit_coid, "reason": reason,
            "link_id": pos.get("link_id"),
        })
        LOG.warning(
            "exit sell for %s already exists at broker "
            "(client_order_id=%s) — adopted order %s",
            symbol, exit_coid, existing,
        )
        return True

    try:
        resp = _submit_sell()
    except Exception as e:
        LOG.exception(
            "exit submission failed for %s: %s", symbol, e,
        )
        # Outcome unknown — same client_order_id next attempt. If the
        # order actually landed, adopt it now (or on the retry, when
        # the duplicate rejection routes back through adoption).
        if _adopt_existing_exit():
            return True
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        return False
    http_status = (resp or {}).get("_http_status") if isinstance(
        resp, dict,
    ) else None
    if http_status not in (200, 201):
        if _adopt_existing_exit():
            return True
        LOG.error(
            "market-sell rejected for %s (status=%s); reverting to "
            "'filled' so the next pass can retry: %s",
            symbol, http_status, resp,
        )
        # Confirmed rejection with no existing order — the coid was
        # burned; the retry must use a fresh one.
        pos["exit_attempt"] = attempt + 1
        pos["status"] = "filled"
        pos.pop("exit_reason_pending", None)
        pos.pop("exit_pending_at", None)
        return False
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    exit_id = data.get("order_id") or data.get("id") or ""
    if not exit_id:
        if _adopt_existing_exit():
            return True
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
    pos["exit_client_order_id"] = exit_coid
    pos["exit_submitted_at"] = _iso(_now_utc())
    pos.pop("exit_reason_pending", None)
    pos.pop("exit_pending_at", None)
    _emit_ledger_v2(cfg, "exit_submitted", {
        "symbol": symbol, "exit_order_id": exit_id,
        "client_order_id": exit_coid,
        "reason": reason, "time_in_force": time_in_force,
        "link_id": pos.get("link_id"),
    })
    return True


def _find_order_id_by_coid(
    oa_client, http, api_key: str, client_order_id: str,
) -> str:
    """Scan the broker order list for a row whose client_order_id
    matches. Returns the broker order id, or "" when absent /
    unavailable."""
    fetch_all = getattr(oa_client, "fetch_all_orders", None)
    if not callable(fetch_all) or not client_order_id:
        return ""
    try:
        rows = fetch_all(http, api_key)
    except Exception as e:
        LOG.warning(
            "coid lookup fetch failed for %s: %s", client_order_id, e,
        )
        return ""
    for row in rows or []:
        if str(row.get("client_order_id") or "") == str(client_order_id):
            return str(row.get("id") or row.get("order_id") or "")
    return ""


def _parse_hhmm(value, fallback: dt_time) -> dt_time:
    """Parse an "HH:MM" config string to a time; fallback on garbage."""
    try:
        hh, mm = str(value).split(":")
        return dt_time(int(hh), int(mm))
    except Exception:
        return fallback


# Venue session-timings cache: {ET date_iso: timings dict | None}.
# None = the last fetch failed; retried no more often than every
# _TIMINGS_RETRY_S seconds. Old dates are pruned on each lookup.
_SESSION_TIMINGS_CACHE: dict[str, dict | None] = {}
_TIMINGS_LAST_ATTEMPT: dict[str, float] = {}
_TIMINGS_RETRY_S = 300.0

#: The regular US-equity close the configured absolute times are
#: anchored to — exit_time / session.end become offsets from this.
_REGULAR_CLOSE = dt_time(16, 0)


def _session_timings_for_today(
    cfg: dict, *, oa_client, api_key: str, http, now_et,
) -> dict | None:
    """Venue session timings for now_et's ET date, cached per date.
    Fetch failures cache None and are retried no more often than
    every ``_TIMINGS_RETRY_S`` seconds. Returns None when the client
    has no ``fetch_calendar_timings`` (legacy surrogates) — callers
    fall back to the legacy fixed window."""
    date_iso = now_et.date().isoformat()
    if date_iso in _SESSION_TIMINGS_CACHE:
        cached = _SESSION_TIMINGS_CACHE[date_iso]
        if cached is not None:
            return cached
        if (time.monotonic() - _TIMINGS_LAST_ATTEMPT.get(date_iso, 0.0)
                < _TIMINGS_RETRY_S):
            return None
    fetch = getattr(oa_client, "fetch_calendar_timings", None)
    if not callable(fetch):
        return None
    _TIMINGS_LAST_ATTEMPT[date_iso] = time.monotonic()
    venue = (cfg.get("execution") or {}).get("default_venue_code", "XNAS")
    try:
        timings = fetch(http, api_key, venue_code=venue,
                        date_iso=date_iso)
    except Exception as e:
        LOG.warning("session timings fetch raised: %s", e)
        timings = None
    _SESSION_TIMINGS_CACHE[date_iso] = (
        timings if isinstance(timings, dict) else None
    )
    for stale in [k for k in _SESSION_TIMINGS_CACHE if k != date_iso]:
        _SESSION_TIMINGS_CACHE.pop(stale, None)
        _TIMINGS_LAST_ATTEMPT.pop(stale, None)
    return _SESSION_TIMINGS_CACHE[date_iso]


def _in_time_stop_window(now_et, cfg: dict, timings: dict | None = None,
                          ) -> bool:
    """True only inside the end-of-session time-stop window. Time
    stops must fire as in-session market sells — never overnight
    (which would cancel OCO protection while the market is closed and
    queue a sell for the open).

    With venue ``timings`` available the window anchors to the ACTUAL
    session close: the configured ``exits.time_stop.exit_time``
    (15:15) and ``session.end`` (15:55) are interpreted as offsets
    from the regular 16:00 close (⇒ close−45m .. close−5m), so an
    early close shifts the window (13:00 close ⇒ 12:15–12:55) and a
    holiday (``is_open`` false) fires nothing. Without timings the
    legacy weekday + absolute-times window applies as the fail-safe."""
    ts_cfg = (cfg.get("exits") or {}).get("time_stop") or {}
    if not ts_cfg.get("enabled", True):
        return False
    start_t = _parse_hhmm(ts_cfg.get("exit_time", "15:15"),
                          dt_time(15, 15))
    end_t = _parse_hhmm((cfg.get("session") or {}).get("end", "15:55"),
                        dt_time(15, 55))
    if isinstance(timings, dict):
        if not timings.get("is_open", False):
            return False
        close_raw = timings.get("session_close")
        if close_raw:
            try:
                close = pd.Timestamp(close_raw)
                if close.tzinfo is None:
                    close = close.tz_localize("UTC")
                now_ts = pd.Timestamp(now_et)
                if now_ts.tzinfo is None:
                    now_ts = now_ts.tz_localize("America/New_York")
                anchor = datetime(2000, 1, 3, _REGULAR_CLOSE.hour,
                                  _REGULAR_CLOSE.minute)
                start_off = anchor - datetime(
                    2000, 1, 3, start_t.hour, start_t.minute,
                )
                end_off = anchor - datetime(
                    2000, 1, 3, end_t.hour, end_t.minute,
                )
                return (close - start_off) <= now_ts <= (close - end_off)
            except Exception:
                LOG.warning(
                    "unusable session_close %r — using the legacy "
                    "fixed window", close_raw,
                )
        # is_open true but no usable close → legacy window below.
    if now_et.weekday() >= 5:
        return False
    return start_t <= now_et.time() <= end_t


def run_time_stop_pass_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
    now_et=None, timings=None,
) -> list[str]:
    """Walk filled positions; exit those whose hold has reached
    max_hold_days. Fires only inside the in-session time-stop window
    (see _in_time_stop_window) — kill switches and the protected-
    position invariant remain 24/7 elsewhere. ``now_et`` and
    ``timings`` are injectable for tests; when ``timings`` is None
    the per-date cache fetches the venue session once per day
    (holiday + early-close aware), falling back to the legacy fixed
    window on any failure. Returns the symbols time-stopped this
    pass."""
    out: list[str] = []
    if now_et is None:
        now_et = pd.Timestamp.now(tz="America/New_York")
    if timings is None:
        try:
            timings = _session_timings_for_today(
                cfg, oa_client=oa_client, api_key=api_key, http=http,
                now_et=now_et,
            )
        except Exception:
            LOG.exception("session timings lookup raised")
            timings = None
    if not _in_time_stop_window(now_et, cfg, timings):
        return out
    max_hold = int((cfg.get("exits") or {}).get("max_hold_days", 3))
    today_et = now_et.date()
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        symbol = pos.get("symbol", "")
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


def _fade_severity(fade_magnitude: float, thresholds: dict) -> str:
    """Highest severity whose threshold <= fade_magnitude, else
    'none'. Severities rank by their threshold value (soft < hard <
    critical in the shipped config)."""
    best_name = "none"
    best_thr = None
    for name, thr in (thresholds or {}).items():
        try:
            thr_f = float(thr)
        except (TypeError, ValueError):
            continue
        if fade_magnitude >= thr_f and (best_thr is None
                                        or thr_f >= best_thr):
            best_name, best_thr = str(name), thr_f
    return best_name


def _et_session_datetime(now_et, t: dt_time):
    """Build an ET tz-aware timestamp for today's session at time t."""
    d = now_et.date()
    return pd.Timestamp(
        year=d.year, month=d.month, day=d.day,
        hour=t.hour, minute=t.minute, tz="America/New_York",
    )


def _signal_fade_eval(
    state: dict, cfg: dict, sf: dict, *,
    active: bool, now_et, phase: str,
    oa_client, api_key: str, http,
) -> list[str]:
    """Score every filled lot's current forming-session signal against
    its entry score. Telemetry rows always; exits only when ``active``
    and the severity is in ``exit_on``."""
    exited: list[str] = []
    score_cfg = cfg.get("score") or {}
    thresholds = sf.get("score_thresholds") or {}
    exit_on = set(sf.get("exit_on") or [])
    fallback_share = float(
        ((cfg.get("historical_features") or {}).get("volume_curve")
         or {}).get("fallback_opening_15m_share", 0.08),
    )
    start_et = _et_session_datetime(now_et, dt_time(9, 45))
    end_ts = pd.Timestamp(now_et)
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("America/New_York")
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        if pos.get("status") != "filled":
            continue
        symbol = pos.get("symbol", "")
        try:
            entry_score = float(pos.get("signal_strength"))
        except (TypeError, ValueError):
            entry_score = 0.0
        if entry_score <= 0:
            LOG.info(
                "signal fade: %s has no usable entry score — skipped",
                symbol,
            )
            continue
        baselines = pos.get("prior_daily_baselines")
        if not isinstance(baselines, dict) or not baselines:
            LOG.info(
                "signal fade: %s lot predates baseline capture — "
                "skipped", symbol,
            )
            continue
        venue = pos.get("venue_code") or (cfg.get("execution") or {}).get(
            "default_venue_code", "XNAS",
        )
        try:
            bars = oa_client.fetch_bars(
                http, api_key, venue_code=venue, symbol=symbol,
                interval="1m", start=start_et, end=end_ts,
            )
        except Exception as e:
            LOG.warning(
                "signal fade: bars fetch failed for %s: %s", symbol, e,
            )
            continue
        if bars is None or len(bars) == 0:
            LOG.warning(
                "signal fade: no session bars for %s — skipped", symbol,
            )
            continue
        sess = features.aggregate_forming_session_bar(bars)
        # Fallback volume curve: the strategy process doesn't load the
        # parquet curve; compute_volume_curve_fraction(None, ...) uses
        # the flat-rate fallback which is adequate for a relative
        # entry-vs-now score comparison.
        vcf = features.compute_volume_curve_fraction(
            None, end_ts, "fallback",
            fallback_opening_15m_share=fallback_share,
        )
        feats = features.compute_forming_session_features(
            sess, baselines, vcf,
        )
        current_score = features.compute_signal_strength(
            feats, score_cfg,
            ema_slope_prior=baselines.get("ema_slope_prior"),
        )
        fade = max(0.0, 1.0 - float(current_score) / entry_score)
        severity = _fade_severity(fade, thresholds)
        would_exit = severity in exit_on
        row = {
            "ts": _iso(_now_utc()), "phase": phase, "symbol": symbol,
            "link_id": pos.get("link_id"),
            "entry_score": entry_score,
            "current_score": float(current_score),
            "fade_magnitude": fade, "severity": severity,
            "would_exit": would_exit, "mode": (
                "active" if active else "telemetry"
            ),
        }
        emit_counterfactual_exit(cfg, row)
        _emit_ledger_v2(cfg, "signal_fade_telemetry", row)
        if not (active and would_exit):
            continue
        limit_price = None
        if sf.get("order_style") == "marketable_limit":
            quote = None
            try:
                quote = oa_client.fetch_quote(
                    http, api_key, venue_code=venue, symbol=symbol,
                )
            except Exception:
                LOG.exception(
                    "signal fade: quote fetch raised for %s", symbol,
                )
            bid = (quote or {}).get("bid")
            if isinstance(bid, (int, float)) and bid > 0:
                offset = float(sf.get(
                    "marketable_limit_offset_pct", 0.005,
                ))
                limit_price = round(float(bid) * (1.0 - offset), 2)
        ok = trigger_exit_v2(
            symbol, pos, cfg,
            oa_client=oa_client, api_key=api_key, http=http,
            reason="signal_fade", time_in_force="DAY",
            order_style=sf.get("order_style", "market"),
            limit_price=limit_price,
        )
        if ok:
            exited.append(symbol)
    return exited


def _capture_candidate_minute_bars(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http, now_et,
) -> list[Path]:
    """research.candidate_minute_bars — once per session (post-close
    pass) write each entered symbol's 1m bars over
    [window.premarket_start, window.session_end] to
    ``<output_dir>/<session_date>/<symbol>.parquet``. ``on_missing:
    warn`` logs and continues; never raises."""
    rc = ((cfg.get("research") or {}).get("candidate_minute_bars")
          or {})
    if not rc.get("enabled", False):
        return []
    window = rc.get("window") or {}
    pm_start = _parse_hhmm(window.get("premarket_start", "08:00"),
                           dt_time(8, 0))
    sess_end = _parse_hhmm(window.get("session_end", "16:00"),
                           dt_time(16, 0))
    columns = list(rc.get("columns") or [])
    out_base = rc.get("output_dir")
    if out_base:
        base_dir = Path(out_base)
        if not base_dir.is_absolute():
            base_dir = paths.REPO_ROOT / base_dir
    else:
        base_dir = paths.CANDIDATE_MINUTE_BARS_DIR
    session_date = now_et.date().isoformat()
    venue = (cfg.get("execution") or {}).get(
        "default_venue_code", "XNAS",
    )
    start_ts = _et_session_datetime(now_et, pm_start)
    end_ts = _et_session_datetime(now_et, sess_end)
    written: list[Path] = []
    for symbol in dict.fromkeys(state.get("entered_today") or []):
        try:
            bars = oa_client.fetch_bars(
                http, api_key, venue_code=venue, symbol=symbol,
                interval="1m", start=start_ts, end=end_ts,
            )
        except Exception as e:
            LOG.warning(
                "candidate bars capture: fetch failed for %s: %s",
                symbol, e,
            )
            continue
        if bars is None or len(bars) == 0:
            LOG.warning(
                "candidate bars capture: no bars for %s on %s",
                symbol, session_date,
            )
            continue
        keep = [c for c in columns if c in bars.columns]
        frame = bars[keep] if keep else bars
        out_path = base_dir / session_date / f"{symbol}.parquet"
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out_path)
        except Exception:
            LOG.exception(
                "candidate bars capture: write failed for %s", symbol,
            )
            continue
        written.append(out_path)
    if written:
        LOG.info(
            "candidate minute bars captured for %d symbol(s) -> %s",
            len(written), base_dir / session_date,
        )
    return written


def run_signal_fade_pass_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
    now_et=None,
) -> list[str]:
    """exits.signal_fade — telemetry-first fade evaluation.

    Two once-per-session passes on business days:
    - at/after ``eval_time`` (15:45): score each filled lot; exits
      fire ONLY when ``signal_fade.active`` is true (default false —
      ``initial_mode: telemetry_then_active_after_validation``).
    - at/after ``telemetry_time`` (16:05): post-close telemetry-only
      snapshot for research, plus the candidate-minute-bars capture.

    Returns symbols exited by the eval pass (always [] in telemetry
    mode)."""
    sf = (cfg.get("exits") or {}).get("signal_fade") or {}
    if not sf.get("enabled", False):
        return []
    if now_et is None:
        now_et = pd.Timestamp.now(tz="America/New_York")
    if now_et.weekday() >= 5:
        return []
    session_date = now_et.date().isoformat()
    exited: list[str] = []
    eval_time = _parse_hhmm(sf.get("eval_time", "15:45"),
                            dt_time(15, 45))
    telemetry_time = _parse_hhmm(sf.get("telemetry_time", "16:05"),
                                 dt_time(16, 5))
    if (now_et.time() >= eval_time
            and state.get("signal_fade_evaluated_on") != session_date):
        # Stamp AFTER the eval returns — an exception leaves the day
        # unstamped so the next tick retries instead of silently
        # skipping the whole session's fade pass.
        exited = _signal_fade_eval(
            state, cfg, sf,
            active=bool(sf.get("active", False)),
            now_et=now_et, phase="eval",
            oa_client=oa_client, api_key=api_key, http=http,
        )
        state["signal_fade_evaluated_on"] = session_date
    if (now_et.time() >= telemetry_time
            and state.get("signal_fade_telemetry_on") != session_date):
        _signal_fade_eval(
            state, cfg, sf, active=False, now_et=now_et,
            phase="post_close",
            oa_client=oa_client, api_key=api_key, http=http,
        )
        state["signal_fade_telemetry_on"] = session_date
        try:
            _capture_candidate_minute_bars(
                state, cfg,
                oa_client=oa_client, api_key=api_key, http=http,
                now_et=now_et,
            )
        except Exception:
            LOG.exception("candidate minute bars capture raised")
    return exited


def execute_kill_l2_v2(
    state: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> list[str]:
    """L2 (KILL_SOFT.flag): market-out every position. For
    pending-fill positions, best-effort cancel parent + children."""
    state["kill_switch_state"] = "L2"
    out: list[str] = []
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        symbol = pos.get("symbol", "")
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
            # Restore the exposure the pending lot reserved (same
            # guarded arithmetic as the janitor) — popping without it
            # left gross_exposure_dollars permanently inflated.
            exposure = pos.get("recorded_exposure")
            if not isinstance(exposure, (int, float)) or isinstance(
                exposure, bool,
            ):
                exposure = 0.0
            state["gross_exposure_dollars"] = max(
                0.0,
                float(state.get("gross_exposure_dollars", 0.0))
                - float(exposure),
            )
            state["open_positions"].pop(pos_id, None)
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
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        symbol = pos.get("symbol", "")
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
    max_attempts = pp.get("max_oco_attach_attempts")
    fallback_stop = bool(pp.get("fallback_stop_enabled", False))
    out: list[str] = []
    now = _now_utc()
    for pos_id, pos in dict(state.get("open_positions") or {}).items():
        symbol = pos.get("symbol", "")
        if pos.get("status") != "filled":
            continue
        children = pos.get("child_order_ids") or {}
        if children.get("target") and children.get("stop"):
            continue
        # OCO attach retries exhausted: act immediately — don't wait
        # for max_unprotected_seconds while attach keeps failing.
        attempts = int(pos.get("oco_attach_attempts", 0) or 0)
        exhausted = (max_attempts is not None
                     and attempts >= int(max_attempts))
        if exhausted and flatten:
            emit_protection_state(cfg, {
                "ts": _iso(now), "symbol": symbol,
                "event": "oco_attach_attempts_exhausted",
                "attempts": attempts,
            })
            ok = trigger_exit_v2(
                symbol, pos, cfg,
                oa_client=oa_client, api_key=api_key, http=http,
                reason="protected_position_flatten",
                time_in_force="DAY",
            )
            if ok:
                out.append(symbol)
            continue
        if (exhausted and not flatten and fallback_stop
                and not pos.get("fallback_stop_attached")):
            _attach_fallback_stop(
                symbol, pos, cfg,
                oa_client=oa_client, api_key=api_key, http=http,
            )
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


def _attach_fallback_stop(
    symbol: str, pos: dict, cfg: dict, *,
    oa_client, api_key: str, http,
) -> bool:
    """Attach a standalone STOP sell at entry x (1 - stop_pct) after
    the OCO attach exhausted its retries and flattening is disabled
    (protected_position.fallback_stop_enabled). Records the id as
    child_order_ids['stop'] so the exit machinery manages it."""
    entry_price = pos.get("entry_price")
    qty = int(pos.get("qty") or 0)
    stop_pct = float(pos.get("stop_pct") or 0.08)
    if not entry_price or float(entry_price) <= 0 or qty <= 0:
        return False
    trigger = round(float(entry_price) * (1.0 - stop_pct), 2)
    venue = pos.get("venue_code") or (cfg.get("execution") or {}).get(
        "default_venue_code", "XNAS",
    )
    tif = (cfg.get("exits") or {}).get("oco_time_in_force", "GTC")
    try:
        resp = oa_client.submit_stop_sell(
            http, api_key, venue_code=venue, symbol=symbol, qty=qty,
            trigger_price=trigger, time_in_force=tif,
        )
    except Exception:
        LOG.exception("fallback stop submission raised for %s", symbol)
        return False
    status = (resp or {}).get("_http_status") if isinstance(
        resp, dict,
    ) else None
    if status not in (200, 201):
        LOG.error(
            "fallback stop rejected for %s (status=%s): %s",
            symbol, status, resp,
        )
        return False
    data = (resp.get("data") or {}) if isinstance(resp, dict) else {}
    stop_id = data.get("order_id") or data.get("id") or ""
    if not stop_id:
        LOG.error(
            "fallback stop accepted for %s but no order_id surfaced: %s",
            symbol, resp,
        )
        return False
    pos.setdefault("child_order_ids", {})["stop"] = stop_id
    pos["stop_price"] = trigger
    pos["fallback_stop_attached"] = True
    _emit_ledger_v2(cfg, "fallback_stop_attached", {
        "symbol": symbol, "link_id": pos.get("link_id"),
        "stop_id": stop_id, "trigger_price": trigger,
    })
    emit_protection_state(cfg, {
        "ts": _iso(_now_utc()), "symbol": symbol,
        "event": "fallback_stop_attached",
        "stop_id": stop_id, "trigger_price": trigger,
    })
    LOG.warning(
        "fallback STOP attached for %s at %.2f (OCO attach exhausted)",
        symbol, trigger,
    )
    return True


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
    # httpx logs one INFO line per request — the 5s poll loop turns
    # that into tens of MB/day of noise in the err log.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        import bowaka_v2_config_schema as config_schema
        config_schema.validate_config(cfg)
    except Exception as e:
        LOG.error("config validation error: %s", e)
        return 5
    try:
        validate_startup_config(cfg)
    except ConfigError as e:
        LOG.error("config error: %s", e)
        return 5

    paths.ensure_dirs()
    persist_config_snapshot(cfg)

    state_path = _resolve(cfg, "state_path", paths.V2_STATE_PATH)
    state, state_parse_failed = load_state_with_recovery(state_path)
    state.setdefault("last_consumed_event_offset", 0)
    state.setdefault("entered_today", [])
    state.setdefault("daily_entries_count", 0)
    state.setdefault("open_positions", {})
    # Compounding bankroll: reconcile lifetime realized PnL from the
    # append-only closure ledger (the source of truth). Heals a torn or
    # lost state.json, a .bak restore, and the closure-append/state-write
    # crash window — any of which would otherwise silently mis-state the
    # sizing bankroll and the floor-halt decision. On first upgrade this
    # seeds the lifetime sum from existing trade history.
    _reconcile_cumulative_from_ledger(state, cfg)
    # Migrate legacy symbol-keyed open_positions to link_id keying so a
    # symbol can carry multiple lots without overwriting (orphaning) one.
    state["open_positions"] = _migrate_open_positions(
        state.get("open_positions") or {}
    )
    # Recompute gross exposure from the lots actually held (heals a
    # zeroed or drifted value from an older build).
    state["gross_exposure_dollars"] = _recompute_gross_exposure(state)

    if args.replay_from:
        # Point the consumer at a different candidate-events file.
        cfg.setdefault("paths", {})["candidate_events_path"] = str(
            Path(args.replay_from).resolve()
        )

    one_shot = args.dry_run or args.once or args.replay_from is not None
    if one_shot:
        if state_parse_failed:
            # Never overwrite an unrecoverable state.json with an empty
            # one from a one-shot invocation — leave it for triage.
            LOG.error(
                "state.json unrecoverable — one-shot run aborted "
                "without writing state (exit 7)",
            )
            return 7
        summary = consume_candidate_events(state, cfg)
        LOG.info("v2 consumer tick: %s", summary)
        _write_state_atomic(state, state_path)
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

        def submit_supplier(symbol: str, qty: int, quote=None,  # noqa: F811
                             link_id=None):
            exec_cfg = cfg.get("execution") or {}
            style = exec_cfg.get("parent_order_style", "market")
            ask = (quote or {}).get("ask")
            if (style == "marketable_limit"
                    and isinstance(ask, (int, float)) and ask > 0):
                slippage = float(exec_cfg.get(
                    "marketable_limit_slippage_pct", 0.005,
                ))
                return oa.submit_limit_buy(
                    live_client, api_key,
                    venue_code=_venue_for(symbol), symbol=symbol,
                    qty=qty,
                    price=round(float(ask) * (1.0 + slippage), 2),
                    time_in_force="DAY",
                    client_order_id=link_id,
                )
            # Default (and marketable-limit-without-a-quote fallback).
            return oa.submit_market_buy(
                live_client, api_key,
                venue_code=_venue_for(symbol), symbol=symbol,
                qty=qty, time_in_force="DAY",
                client_order_id=link_id,
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

    # Broker-truth reconciliation before the first trade decision.
    # Exit code 7 = refuse to trade blind (watchdog must NOT restart).
    if live_client and oa_module is not None:
        try:
            rc = reconcile_with_broker(
                state, cfg,
                oa_client=oa_module, api_key=api_key, http=live_client,
                state_parse_failed=state_parse_failed,
            )
        except Exception:
            LOG.exception("broker reconciliation raised (continuing)")
            rc = None
        if rc is not None:
            _write_state_atomic(state, state_path)
            live_client.close()
            return rc
        # Startup recovery for lots a prior crash stranded in
        # exit_pending — must run before the first management pass.
        try:
            recover_stuck_exit_pending(
                state, cfg,
                oa_client=oa_module, api_key=api_key, http=live_client,
            )
        except Exception:
            LOG.exception("startup exit_pending recovery raised")
    elif state_parse_failed:
        LOG.error(
            "state.json unrecoverable and no live client to verify "
            "broker positions — refusing to run (exit 7)",
        )
        return 7

    def _persist_now() -> None:
        """Immediate mid-tick persist — narrows the exit double-fire
        crash window after a management pass mutates positions."""
        try:
            _write_state_atomic(state, state_path)
        except Exception as e:
            LOG.warning("mid-tick state persist failed: %s", e)

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
            _write_state_atomic(state, state_path)
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
                        flattened = execute_kill_l2_v2(
                            state, cfg,
                            oa_client=oa_module, api_key=api_key,
                            http=live_client,
                        )
                        if flattened:
                            _persist_now()
                    except Exception:
                        LOG.exception("L2 flatten raised")
        elif state.get("kill_switch_state") == "L2":
            # Operator cleared the flag — release the L2 mark so future
            # blocks behave normally.
            state.pop("kill_switch_state", None)

        # Session rollover runs unconditionally — L1 KILL_NEW skips the
        # consume pass below, but per-day counters must still reset
        # when the ET date advances under an active flag.
        try:
            roll_session_if_needed(state, _now_utc(), _today_iso())
        except Exception:
            LOG.exception("roll_session_if_needed raised")

        # L1 block-new — KILL_NEW.flag prevents new entries; existing
        # positions keep their brackets / time-stops running.
        l1_block_new = (switch_dir / "KILL_NEW.flag").exists()

        try:
            if not l1_block_new:
                summary = consume_candidate_events(
                    state, cfg,
                    quote_supplier=quote_supplier,
                    submit_supplier=submit_supplier,
                    state_path=state_path,
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
            # Unknown-submit adjudication runs BEFORE the janitor —
            # the resolver owns outcome_unresolved lots.
            try:
                resolve_unknown_submits(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("resolve_unknown_submits raised")
            try:
                expire_stale_pending_fills(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("expire_stale_pending_fills raised")
            # Recover lots a crash stranded in exit_pending BEFORE the
            # OCO sweep so cleared child ids re-attach this same tick.
            try:
                recover_stuck_exit_pending(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("recover_stuck_exit_pending raised")
            try:
                submit_pending_oco_children_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                )
            except Exception:
                LOG.exception("submit_pending_oco_children_v2 raised")
            try:
                if enforce_protected_position_invariant_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                ):
                    _persist_now()
            except Exception:
                LOG.exception("enforce_protected_position_invariant_v2 raised")
            try:
                if run_time_stop_pass_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                ):
                    _persist_now()
            except Exception:
                LOG.exception("run_time_stop_pass_v2 raised")
            try:
                if run_signal_fade_pass_v2(
                    state, cfg,
                    oa_client=oa_module, api_key=api_key, http=live_client,
                ):
                    _persist_now()
            except Exception:
                LOG.exception("run_signal_fade_pass_v2 raised")

        try:
            _write_state_atomic(state, state_path)
        except Exception as e:
            LOG.warning("state write failed: %s", e)
        try:
            backup_state_daily(state, state_path)
        except Exception:
            LOG.exception("daily state backup raised")
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
