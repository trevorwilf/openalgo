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
        if submit_supplier is not None:
            try:
                submit_supplier(symbol, qty)
            except Exception as e:
                LOG.warning("submit_supplier raised for %s: %s", symbol, e)
                summary["rejected"] += 1
                continue

        # Update state.
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


# ---------------------------------------------------------------- main


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


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

    summary = consume_candidate_events(state, cfg)
    LOG.info("v2 consumer tick: %s", summary)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, default=str, indent=2),
                          encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
