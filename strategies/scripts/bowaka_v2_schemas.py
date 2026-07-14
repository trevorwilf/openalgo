#!/usr/bin/env python3
"""Bowaka v2 — candidate event + entry decision schemas.

Defines:
- CANDIDATE_EVENT_SCHEMA_VERSION (= 3 per handoff §5.4).
- Required-field manifests for candidate_signal and entry_decision events.
- Validators returning (ok, list_of_problems).
- The CANONICAL_REJECTION_REASONS frozenset (handoff §5.5).
- ``make_event_id`` for canonical event id formatting.

Schema parity: any v2 producer (scanner, replay) and any v2
consumer (strategy, backtester, analysis) must agree on these
constants. Schema-version negotiation lives in Phase 6's
``bowaka_v2_event_stream_versioning.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


CANDIDATE_EVENT_SCHEMA_VERSION: int = 3


# ---- candidate_signal required fields --------------------------------
# Each entry is either a top-level key (str) or a (parent, child)
# tuple naming a required field inside a nested object.

CANDIDATE_EVENT_REQUIRED_FIELDS: tuple[Any, ...] = (
    "schema_version",
    "strategy",
    "event_type",
    "event_id",
    "generated_at",
    "session_date",
    "scan_timestamp",
    "provider",
    "data_feed",
    "bar_interval",
    "config_hash",
    "universe_hash",
    "symbol",
    "exchange",
    "venue_code",
    "instrument_class",
    "eligible_for_bowaka_equity_bucket",
    # prior_daily_baselines: every field per §5.4
    ("prior_daily_baselines", "prior_close"),
    ("prior_daily_baselines", "avg_volume_20d"),
    ("prior_daily_baselines", "avg_dollar_volume_20d"),
    ("prior_daily_baselines", "prior_atr_14d"),
    ("prior_daily_baselines", "prior_atr_pct"),
    ("prior_daily_baselines", "ema_10_prior"),
    ("prior_daily_baselines", "ema_10_lag_3"),
    ("prior_daily_baselines", "ema_slope_prior"),
    # forming_session_bar
    ("forming_session_bar", "session_open"),
    ("forming_session_bar", "session_high"),
    ("forming_session_bar", "session_low"),
    ("forming_session_bar", "last_price"),
    ("forming_session_bar", "session_volume"),
    ("forming_session_bar", "session_range"),
    ("forming_session_bar", "last_bar_timestamp"),
    # intraday_volume_context
    ("intraday_volume_context", "volume_curve_fraction"),
    ("intraday_volume_context", "expected_volume_until_scan"),
    ("intraday_volume_context", "rvol_so_far"),
    ("intraday_volume_context", "projected_full_day_rvol"),
    # features
    ("features", "gap_pct"),
    ("features", "current_return_pct"),
    ("features", "range_expansion_so_far"),
    ("features", "close_location_so_far"),
    ("features", "ema_distance"),
    ("features", "ema_slope"),
    ("features", "signal_strength"),
    # gate_results
    ("gate_results", "price_gate"),
    ("gate_results", "avg_dollar_volume_gate"),
    ("gate_results", "rvol_gate"),
    ("gate_results", "prior_atr_pct_gate"),
    ("gate_results", "range_expansion_gate"),
    ("gate_results", "close_location_gate"),
    ("gate_results", "ema_distance_gate"),
    ("gate_results", "ema_slope_gate"),
    ("gate_results", "max_gap_gate"),
    ("gate_results", "instrument_gate"),
    "candidate_rank",
    "signal_expiry_timestamp",
)


# ---- entry_decision required fields ---------------------------------

ENTRY_DECISION_REQUIRED_FIELDS: tuple[Any, ...] = (
    "schema_version",
    "strategy",
    "event_type",
    "decision",                  # "accepted" | "rejected"
    "reason",                    # in CANONICAL_REJECTION_REASONS or "all_gates_passed"
    "event_id",
    "candidate_event_id",
    "session_date",
    "symbol",
    "entry_trigger",
    "scan_timestamp",
    "decision_timestamp",
    # quote snapshot
    ("quote", "bid"),
    ("quote", "ask"),
    ("quote", "mid"),
    ("quote", "spread_pct"),
    ("quote", "quote_timestamp"),
    ("quote", "quote_age_seconds"),
    # risk_snapshot
    ("risk_snapshot", "bankroll"),
    ("risk_snapshot", "gross_exposure_dollars"),
    ("risk_snapshot", "gross_exposure_pct"),
    ("risk_snapshot", "entries_today"),
    ("risk_snapshot", "open_positions"),
    ("risk_snapshot", "candidate_adv"),
    ("risk_snapshot", "target_notional"),
    ("risk_snapshot", "adv_participation_frac"),
    # order_plan
    ("order_plan", "side"),
    ("order_plan", "order_style"),
    ("order_plan", "qty"),
    ("order_plan", "estimated_notional"),
    ("order_plan", "stop_pct"),
    ("order_plan", "target_pct"),
    ("order_plan", "max_hold_days"),
)


# ---- canonical rejection reasons (handoff §5.5) ----------------------

CANONICAL_REJECTION_REASONS: frozenset[str] = frozenset({
    "data_feed_mismatch",
    "stale_bar",
    "missing_daily_baseline",
    "instrument_ineligible",
    "halt_or_pending_review",
    "same_symbol_already_entered_today",
    "symbol_cooldown",
    "daily_entry_cap",
    "max_concurrent_positions",
    "gross_exposure_cap",
    "adv_cap",
    "spread_too_wide",
    "quote_stale",
    "price_chase_band",
    "lost_signal_before_entry",
    "past_last_entry_time",
    "kill_switch",
    "broker_reject",
    "invalid_signal_price",
    "max_stopouts_per_day",
    "consecutive_stopouts",
    "strategy_slice_loss",
    "max_entries_per_scan",
    # Fix Phase 4 — entries blocked while a submit's outcome is
    # unknown (resolver adjudicating a raised / id-less submit).
    "unresolved_order_outcome",
})


# ---- validators ------------------------------------------------------


def _missing(d: dict, key: Any) -> str | None:
    """Return a problem string if ``d`` is missing ``key``, else None."""
    if isinstance(key, tuple):
        parent, child = key
        if not isinstance(d.get(parent), dict):
            return f"missing nested object {parent!r}"
        if child not in d[parent] or d[parent][child] is _MISSING:
            return f"missing required field {parent}.{child}"
        return None
    if key not in d or d[key] is _MISSING:
        return f"missing required field {key!r}"
    return None


_MISSING = object()


def _check_required(d: dict, fields: Iterable[Any]) -> list[str]:
    problems: list[str] = []
    for f in fields:
        m = _missing(d, f)
        if m:
            problems.append(m)
    return problems


def validate_candidate_event(d: dict) -> tuple[bool, list[str]]:
    """Validate a candidate_signal event against schema v3."""
    if not isinstance(d, dict):
        return False, ["not a dict"]
    problems = _check_required(d, CANDIDATE_EVENT_REQUIRED_FIELDS)
    # Spot-check critical fields.
    if d.get("schema_version") != CANDIDATE_EVENT_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {CANDIDATE_EVENT_SCHEMA_VERSION!r}, "
            f"got {d.get('schema_version')!r}"
        )
    if d.get("event_type") != "candidate_signal":
        problems.append(
            f"event_type must be 'candidate_signal', got {d.get('event_type')!r}"
        )
    return (len(problems) == 0), problems


def validate_entry_decision(d: dict) -> tuple[bool, list[str]]:
    """Validate an entry_decision event."""
    if not isinstance(d, dict):
        return False, ["not a dict"]
    problems = _check_required(d, ENTRY_DECISION_REQUIRED_FIELDS)
    if d.get("schema_version") != CANDIDATE_EVENT_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {CANDIDATE_EVENT_SCHEMA_VERSION!r}, "
            f"got {d.get('schema_version')!r}"
        )
    if d.get("event_type") != "entry_decision":
        problems.append(
            f"event_type must be 'entry_decision', got {d.get('event_type')!r}"
        )
    decision = d.get("decision")
    if decision not in ("accepted", "rejected"):
        problems.append(
            f"decision must be 'accepted' or 'rejected', got {decision!r}"
        )
    reason = d.get("reason")
    if decision == "rejected" and reason not in CANONICAL_REJECTION_REASONS:
        problems.append(
            f"reason {reason!r} is not in CANONICAL_REJECTION_REASONS"
        )
    return (len(problems) == 0), problems


# ---- canonical event id ---------------------------------------------


def make_event_id(
    strategy: str, session_date: str, symbol: str, ts: str | datetime,
    *, suffix: str | None = None,
) -> str:
    """Build a canonical event_id of the form
    ``<strategy>:<session_date>:<symbol>[:<suffix>]:<iso_ts>``.

    Mirrors the format in handoff §5.4 example:
    ``bowaka_v2:2026-05-18:XYZ:2026-05-18T14:35:00Z`` and §5.5
    example ``bowaka_v2:2026-05-18:XYZ:entry:2026-05-18T14:35:05Z``.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        ts_str = str(ts)
    if suffix:
        return f"{strategy}:{session_date}:{symbol}:{suffix}:{ts_str}"
    return f"{strategy}:{session_date}:{symbol}:{ts_str}"


__all__ = [
    "CANDIDATE_EVENT_SCHEMA_VERSION",
    "CANDIDATE_EVENT_REQUIRED_FIELDS",
    "ENTRY_DECISION_REQUIRED_FIELDS",
    "CANONICAL_REJECTION_REASONS",
    "validate_candidate_event",
    "validate_entry_decision",
    "make_event_id",
]
