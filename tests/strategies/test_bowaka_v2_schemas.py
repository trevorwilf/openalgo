"""Phase 1 — bowaka_v2_schemas validators + canonical rejection set."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

import bowaka_v2_schemas as schemas


_VALID_CANDIDATE = {
    "schema_version": 3,
    "strategy": "bowaka_v2",
    "event_type": "candidate_signal",
    "event_id": "bowaka_v2:2026-05-18:XYZ:2026-05-18T14:35:00Z",
    "generated_at": "2026-05-18T14:35:02Z",
    "session_date": "2026-05-18",
    "scan_timestamp": "2026-05-18T14:35:00Z",
    "provider": "alpaca",
    "data_feed": "sip",
    "bar_interval": "1m",
    "config_hash": "sha256:abc123",
    "universe_hash": "sha256:def456",
    "symbol": "XYZ",
    "exchange": "NASDAQ",
    "venue_code": "XNAS",
    "instrument_class": "operating_equity",
    "eligible_for_bowaka_equity_bucket": True,
    "prior_daily_baselines": {
        "prior_close": 7.42, "avg_volume_20d": 450000,
        "avg_dollar_volume_20d": 3100000, "prior_atr_14d": 0.52,
        "prior_atr_pct": 0.0701, "ema_10_prior": 7.18,
        "ema_10_lag_3": 7.04, "ema_slope_prior": 0.0199,
    },
    "forming_session_bar": {
        "session_open": 7.61, "session_high": 8.20,
        "session_low": 7.50, "last_price": 8.11,
        "session_volume": 820000, "session_range": 0.70,
        "last_bar_timestamp": "2026-05-18T14:34:00Z",
    },
    "intraday_volume_context": {
        "volume_curve_fraction": 0.42,
        "expected_volume_until_scan": 189000,
        "rvol_so_far": 4.34, "projected_full_day_rvol": 4.34,
    },
    "features": {
        "gap_pct": 0.0256, "current_return_pct": 0.1482,
        "range_expansion_so_far": 1.346,
        "close_location_so_far": 0.871,
        "ema_distance": 0.128, "ema_slope": 0.0199,
        "signal_strength": 7.82,
    },
    "gate_results": {
        "price_gate": True, "avg_dollar_volume_gate": True,
        "rvol_gate": True, "prior_atr_pct_gate": True,
        "range_expansion_gate": True, "close_location_gate": True,
        "ema_distance_gate": True, "ema_slope_gate": True,
        "max_gap_gate": True, "instrument_gate": True,
    },
    "candidate_rank": 1,
    "signal_expiry_timestamp": "2026-05-18T14:45:00Z",
}


_VALID_ENTRY_DECISION = {
    "schema_version": 3,
    "strategy": "bowaka_v2",
    "event_type": "entry_decision",
    "decision": "accepted",
    "reason": "all_gates_passed",
    "event_id": "bowaka_v2:2026-05-18:XYZ:entry:2026-05-18T14:35:05Z",
    "candidate_event_id": "bowaka_v2:2026-05-18:XYZ:2026-05-18T14:35:00Z",
    "session_date": "2026-05-18",
    "symbol": "XYZ",
    "entry_trigger": "forming_daily_bar_scan",
    "scan_timestamp": "2026-05-18T14:35:00Z",
    "decision_timestamp": "2026-05-18T14:35:05Z",
    "quote": {
        "bid": 8.10, "ask": 8.14, "mid": 8.12,
        "spread_pct": 0.0049, "quote_timestamp": "2026-05-18T14:35:04Z",
        "quote_age_seconds": 1,
    },
    "risk_snapshot": {
        "bankroll": 90000, "gross_exposure_dollars": 32000,
        "gross_exposure_pct": 0.356, "entries_today": 4,
        "open_positions": 8, "candidate_adv": 3100000,
        "target_notional": 4000, "adv_participation_frac": 0.00129,
    },
    "order_plan": {
        "side": "buy", "order_style": "market", "qty": 492,
        "estimated_notional": 3995.04, "stop_pct": 0.08,
        "target_pct": 0.15, "max_hold_days": 3,
    },
}


# ---- candidate event -------------------------------------------------


def test_candidate_schema_v3_accepts_valid_event() -> None:
    ok, problems = schemas.validate_candidate_event(_VALID_CANDIDATE)
    assert ok is True, problems
    assert problems == []


def test_candidate_schema_v3_rejects_missing_required_fields() -> None:
    """Drop each required top-level field one at a time and assert
    each rejection lists that field."""
    for field in schemas.CANDIDATE_EVENT_REQUIRED_FIELDS:
        bad = copy.deepcopy(_VALID_CANDIDATE)
        if isinstance(field, tuple):
            parent, child = field
            del bad[parent][child]
            ok, problems = schemas.validate_candidate_event(bad)
            assert ok is False
            assert any(f"{parent}.{child}" in p for p in problems), (
                f"expected problem mentioning {parent}.{child}, got {problems}"
            )
        else:
            del bad[field]
            ok, problems = schemas.validate_candidate_event(bad)
            assert ok is False
            assert any(field in p for p in problems), (
                f"expected problem mentioning {field}, got {problems}"
            )


def test_candidate_schema_rejects_wrong_schema_version() -> None:
    bad = copy.deepcopy(_VALID_CANDIDATE)
    bad["schema_version"] = 2
    ok, problems = schemas.validate_candidate_event(bad)
    assert ok is False
    assert any("schema_version" in p for p in problems)


def test_candidate_schema_rejects_wrong_event_type() -> None:
    bad = copy.deepcopy(_VALID_CANDIDATE)
    bad["event_type"] = "in_play_signal"
    ok, problems = schemas.validate_candidate_event(bad)
    assert ok is False
    assert any("event_type" in p for p in problems)


# ---- canonical rejection reasons ------------------------------------


def test_canonical_rejection_reasons_complete() -> None:
    """Asserts the set equals the handoff §5.5 spec exactly, plus the
    hardening-phase additions (invalid_signal_price and the Phase 4
    risk-control reasons)."""
    expected = {
        "data_feed_mismatch", "stale_bar", "missing_daily_baseline",
        "instrument_ineligible", "halt_or_pending_review",
        "same_symbol_already_entered_today", "symbol_cooldown",
        "daily_entry_cap", "max_concurrent_positions",
        "gross_exposure_cap", "adv_cap", "spread_too_wide",
        "quote_stale", "price_chase_band", "lost_signal_before_entry",
        "past_last_entry_time", "kill_switch", "broker_reject",
        "invalid_signal_price",
        "max_stopouts_per_day", "consecutive_stopouts",
        "strategy_slice_loss", "max_entries_per_scan",
    }
    assert set(schemas.CANONICAL_REJECTION_REASONS) == expected


# ---- entry decision --------------------------------------------------


def test_entry_decision_schema_round_trip() -> None:
    ok, problems = schemas.validate_entry_decision(_VALID_ENTRY_DECISION)
    assert ok is True, problems
    assert problems == []


def test_entry_decision_rejected_uses_canonical_reason() -> None:
    rejected = copy.deepcopy(_VALID_ENTRY_DECISION)
    rejected["decision"] = "rejected"
    rejected["reason"] = "spread_too_wide"
    ok, _ = schemas.validate_entry_decision(rejected)
    assert ok is True

    bad = copy.deepcopy(_VALID_ENTRY_DECISION)
    bad["decision"] = "rejected"
    bad["reason"] = "i_dont_like_it"
    ok, problems = schemas.validate_entry_decision(bad)
    assert ok is False
    assert any("CANONICAL_REJECTION_REASONS" in p for p in problems)


# ---- event id --------------------------------------------------------


def test_make_event_id_canonical_format() -> None:
    eid = schemas.make_event_id(
        "bowaka_v2", "2026-05-18", "XYZ",
        datetime(2026, 5, 18, 14, 35, 0, tzinfo=timezone.utc),
    )
    assert eid == "bowaka_v2:2026-05-18:XYZ:2026-05-18T14:35:00Z"


def test_make_event_id_with_suffix() -> None:
    eid = schemas.make_event_id(
        "bowaka_v2", "2026-05-18", "XYZ",
        "2026-05-18T14:35:05Z", suffix="entry",
    )
    assert eid == "bowaka_v2:2026-05-18:XYZ:entry:2026-05-18T14:35:05Z"
