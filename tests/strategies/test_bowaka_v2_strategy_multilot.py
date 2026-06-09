"""Multi-lot positions — a symbol may be re-entered on consecutive
days up to ``risk.max_lots_per_symbol`` concurrent lots, and a
re-entry can never overwrite (orphan) an existing lot.

Covers:
- ``_migrate_open_positions`` — legacy symbol-keyed state -> link_id keying.
- Two lots of one symbol coexisting after entries on different days.
- The orphan regression: the first lot survives the second entry.
- ``risk.max_lots_per_symbol`` capping accumulation.
- The ADV cap enforced on the *aggregate* symbol position.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import bowaka_v2_strategy as v2
import bowaka_v2_schemas as schemas


# ---------- helpers ----------


def _cand(symbol: str, session_date: str) -> dict:
    """A schema-valid candidate_signal event for ``symbol`` on
    ``session_date``. Expiry is end-of-session so it never reads as
    expired for a same-day consume."""
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:{session_date}:{symbol}:scan",
        "generated_at": f"{session_date}T18:34:00Z",
        "session_date": session_date,
        "scan_timestamp": f"{session_date}T18:34:00Z",
        "provider": "alpaca", "data_feed": "iex", "bar_interval": "1m",
        "config_hash": "sha256:t", "universe_hash": "sha256:t",
        "symbol": symbol, "exchange": "NASDAQ", "venue_code": "XNAS",
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "prior_daily_baselines": {
            "prior_close": 7.42, "avg_volume_20d": 450000,
            "avg_dollar_volume_20d": 3_000_000,
            "prior_atr_14d": 0.52, "prior_atr_pct": 0.0701,
            "ema_10_prior": 7.18, "ema_10_lag_3": 7.04,
            "ema_slope_prior": 0.0199,
        },
        "forming_session_bar": {
            "session_open": 7.61, "session_high": 8.20,
            "session_low": 7.50, "last_price": 8.11,
            "session_volume": 820000, "session_range": 0.70,
            "last_bar_timestamp": f"{session_date}T18:34:00Z",
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
        "signal_expiry_timestamp": f"{session_date}T23:59:00Z",
    }


def _cfg(cand_path) -> dict:
    """Consumer cfg with gates disabled and max_lots_per_symbol = 3."""
    return {
        "strategy": {"mode": "forming_daily_bar_monitor",
                     "environment": "paper"},
        "paths": {"candidate_events_path": str(cand_path)},
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS", "parent_order_style": "market",
            "quote_gate": {"enabled": False},
            "price_chase_gate": {"enabled": False},
            "halt_gate": {"enabled": False},
        },
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {
            "max_total_entries_per_day": 10,
            "max_gross_exposure_pct": 0.80,
            "max_lots_per_symbol": 3,
        },
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3},
        "logging": {k: False for k in (
            "emit_entry_decisions", "emit_rejected_candidates",
            "log_order_execution_quality", "log_protection_state",
            "log_shadow_risk_controls", "log_counterfactual_entries",
            "log_counterfactual_exits",
        )},
    }


def _fresh_state() -> dict:
    return {
        "last_consumed_event_offset": 0, "entered_today": [],
        "daily_entries_count": 0, "open_positions": {},
    }


def _ok_submit(symbol, qty):
    return {"_http_status": 200,
            "data": {"order_id": f"PARENT-{symbol}-{qty}"}}


_QUOTE = {
    "bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
    "quote_timestamp": "2026-05-18T18:35:00Z",
    "quote_age_seconds": 1, "symbol_status": "ok",
}


def _consume(state, cfg, session_date, hh=18):
    return v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: dict(_QUOTE),
        submit_supplier=_ok_submit,
        today_iso=session_date,
        now_utc=datetime(
            int(session_date[:4]), int(session_date[5:7]),
            int(session_date[8:10]), hh, 35, tzinfo=timezone.utc,
        ),
    )


# ---------- _migrate_open_positions ----------


def test_migrate_rekeys_legacy_symbol_shape():
    legacy = {
        "RUM": {"symbol": "RUM", "link_id": "BOWAKAv2-RUM-111", "qty": 100},
        "BLMN": {"symbol": "BLMN", "link_id": "BOWAKAv2-BLMN-222", "qty": 50},
    }
    migrated = v2._migrate_open_positions(legacy)
    assert set(migrated) == {"BOWAKAv2-RUM-111", "BOWAKAv2-BLMN-222"}
    assert migrated["BOWAKAv2-RUM-111"]["symbol"] == "RUM"
    assert migrated["BOWAKAv2-BLMN-222"]["qty"] == 50


def test_migrate_is_idempotent():
    keyed = {
        "BOWAKAv2-RUM-111": {"symbol": "RUM", "link_id": "BOWAKAv2-RUM-111"},
    }
    assert v2._migrate_open_positions(keyed) == keyed
    assert v2._migrate_open_positions({}) == {}


def test_migrate_missing_link_id_keeps_existing_key():
    d = {"X": {"symbol": "X", "qty": 1}}
    assert v2._migrate_open_positions(d) == {"X": {"symbol": "X", "qty": 1}}


# ---------- multi-lot accumulation ----------


def test_two_lots_same_symbol_across_consecutive_days(tmp_path):
    """RUM entered on day 1 and again on day 2 — both lots coexist."""
    cand_path = tmp_path / "candidates.jsonl"
    cfg = _cfg(cand_path)
    state = _fresh_state()

    cand_path.write_text(json.dumps(_cand("RUM", "2026-05-18")) + "\n")
    s1 = _consume(state, cfg, "2026-05-18")
    assert s1["accepted"] == 1
    assert len(v2.lots_for_symbol(state, "RUM")) == 1
    lot1_key = next(iter(state["open_positions"]))

    with open(cand_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(_cand("RUM", "2026-05-19")) + "\n")
    s2 = _consume(state, cfg, "2026-05-19")
    assert s2["accepted"] == 1

    lots = v2.lots_for_symbol(state, "RUM")
    assert len(lots) == 2
    assert len({p["link_id"] for p in lots}) == 2          # distinct lots
    assert len(state["open_positions"]) == 2


def test_second_entry_does_not_orphan_the_first(tmp_path):
    """The orphan regression: the day-1 lot's record is byte-identical
    after the day-2 re-entry — never overwritten."""
    cand_path = tmp_path / "candidates.jsonl"
    cfg = _cfg(cand_path)
    state = _fresh_state()

    cand_path.write_text(json.dumps(_cand("RUM", "2026-05-18")) + "\n")
    _consume(state, cfg, "2026-05-18")
    lot1_key = next(iter(state["open_positions"]))
    lot1_snapshot = dict(state["open_positions"][lot1_key])

    with open(cand_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(_cand("RUM", "2026-05-19")) + "\n")
    _consume(state, cfg, "2026-05-19")

    assert lot1_key in state["open_positions"]              # still present
    assert state["open_positions"][lot1_key] == lot1_snapshot  # untouched


def test_same_day_re_entry_is_still_blocked(tmp_path):
    """One entry per symbol per day — a same-session second RUM
    candidate is deduped, not entered."""
    cand_path = tmp_path / "candidates.jsonl"
    cfg = _cfg(cand_path)
    state = _fresh_state()

    c1 = _cand("RUM", "2026-05-18")
    c2 = _cand("RUM", "2026-05-18")
    c2["event_id"] = "bowaka_v2:2026-05-18:RUM:scan2"
    cand_path.write_text(
        json.dumps(c1) + "\n" + json.dumps(c2) + "\n"
    )
    s = _consume(state, cfg, "2026-05-18")
    assert s["accepted"] == 1
    assert s["dedupe"] == 1
    assert len(v2.lots_for_symbol(state, "RUM")) == 1


def test_max_lots_per_symbol_caps_accumulation(tmp_path):
    """A 4th lot is rejected once 3 are already held."""
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(json.dumps(_cand("RUM", "2026-05-21")) + "\n")
    cfg = _cfg(cand_path)                       # max_lots_per_symbol = 3
    state = _fresh_state()
    state["open_positions"] = {
        f"BOWAKAv2-RUM-{i}": {
            "symbol": "RUM", "qty": 100, "link_id": f"BOWAKAv2-RUM-{i}",
            "status": "filled", "entry_price": 7.0,
        }
        for i in range(3)
    }
    s = _consume(state, cfg, "2026-05-21")
    assert s["accepted"] == 0
    assert s["dedupe"] == 1
    assert len(v2.lots_for_symbol(state, "RUM")) == 3       # unchanged


# ---------- ADV cap aggregates lots ----------


def test_adv_cap_enforced_on_aggregate_symbol_position():
    """The ADV dollar cap counts existing lots of the symbol, so
    stacked lots cannot collectively exceed the liquidity limit."""
    cfg = {
        "risk": {"adv_tier_caps": [
            {"max_adv_dollars": None, "max_position_as_adv_frac": 0.01},
        ]},
        "sizing": {"max_concurrent_positions": 18},
    }
    ev = {"symbol": "RUM"}
    adv = 1_000_000          # cap = 1% = $10,000

    # No existing lots: a $6,000 lot fits under the cap.
    empty = {"open_positions": {}}
    assert v2._risk_gates(
        ev, empty, cfg, candidate_adv=adv, target_notional=6000,
    ) is None

    # One $6,000 lot already held: 6,000 + 6,000 = 12,000 > 10,000.
    held = {"open_positions": {
        "BOWAKAv2-RUM-1": {
            "symbol": "RUM", "qty": 600, "entry_price": 10.0,
        },
    }}
    assert v2._risk_gates(
        ev, held, cfg, candidate_adv=adv, target_notional=6000,
    ) == "adv_cap"


def test_symbol_open_notional_sums_lots():
    state = {"open_positions": {
        "a": {"symbol": "RUM", "qty": 100, "entry_price": 7.0},
        "b": {"symbol": "RUM", "qty": 200, "entry_price": 8.0},
        "c": {"symbol": "BLMN", "qty": 50, "entry_price": 5.0},
    }}
    assert v2._symbol_open_notional(state, "RUM") == 700.0 + 1600.0
    assert v2._symbol_open_notional(state, "BLMN") == 250.0
    assert v2._symbol_open_notional(state, "NONE") == 0.0
