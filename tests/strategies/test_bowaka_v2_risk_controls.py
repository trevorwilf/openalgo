"""Hardening Phase 4 — dead risk-control config keys, now live.

One focused test per control:
- risk.max_stopouts_per_day / stop_trading_after_consecutive_stopouts
- sizing.max_per_trade_dollars / target_risk_dollars
- risk.strategy_slice_loss_pct (v1 archive semantics)
- scanner.max_entries_per_scan / same_symbol_entries_per_day /
  symbol_cooldown_minutes
- scanner.require_fresh_intraday_bar + data.max_bar_age_seconds
- protected_position.max_oco_attach_attempts / fallback_stop_enabled
- logging.emit_feature_snapshots
- the strict config validator (bowaka_v2_config_schema)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import bowaka_v2_config_schema as config_schema
import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                        tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                        tmp_path / "rejected_candidates.jsonl")
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                        tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                        tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                        tmp_path / "daily_summary.jsonl")
    monkeypatch.setattr(p, "FEATURE_SNAPSHOTS_PATH",
                        tmp_path / "feature_snapshots.jsonl")


_NOW = datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc)


def _candidate(symbol: str, *, rank: int = 1,
               scan_ts: str = "2026-05-18T14:35:00Z") -> dict:
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2", "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:{scan_ts}",
        "generated_at": scan_ts, "session_date": "2026-05-18",
        "scan_timestamp": scan_ts, "provider": "alpaca",
        "data_feed": "iex", "bar_interval": "1m",
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
            "last_bar_timestamp": "2026-05-18T18:34:00Z",
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
        "candidate_rank": rank,
        "signal_expiry_timestamp": "2026-05-18T23:59:00Z",
    }


def _cfg(tmp_path, **over):
    cfg = {
        "strategy": {"mode": "forming_daily_bar_monitor",
                     "environment": "paper"},
        "paths": {
            "candidate_events_path": str(tmp_path / "candidates.jsonl"),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS",
            "parent_order_style": "market",
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
        "scanner": {},
        "risk": {"max_total_entries_per_day": 50,
                 "max_gross_exposure_pct": 5.0},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3},
        "logging": {k: False for k in (
            "emit_entry_decisions", "emit_rejected_candidates",
            "log_order_execution_quality", "log_protection_state",
            "log_shadow_risk_controls", "log_counterfactual_entries",
            "log_counterfactual_exits",
        )},
    }
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


def _write(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _fresh_state() -> dict:
    return {"last_consumed_event_offset": 0, "entered_today": [],
            "daily_entries_count": 0, "open_positions": {},
            "gross_exposure_dollars": 0.0}


def _ok_submit(symbol, qty):
    return {"_http_status": 200, "data": {"order_id": f"P-{symbol}"}}


def _decisions(tmp_path) -> list[dict]:
    import bowaka_v2_paths as p
    if not p.ENTRY_DECISIONS_PATH.exists():
        return []
    return [json.loads(l) for l in
            p.ENTRY_DECISIONS_PATH.read_text().splitlines()]


def _closed_lot(symbol="AAA", **over):
    pos = {"symbol": symbol, "qty": 100, "entry_price": 10.0,
           "status": "filled", "link_id": f"L-{symbol}",
           "entry_timestamp": "2026-05-18T13:31:00Z",
           "stop_price": 9.2, "target_price": 11.5,
           "recorded_exposure": 1000.0}
    pos.update(over)
    return pos


# ---- stopout circuit breakers -------------------------------------------


def test_max_stopouts_per_day_blocks_entries(tmp_path):
    cfg = _cfg(tmp_path, risk={"max_total_entries_per_day": 50,
                               "max_gross_exposure_pct": 5.0,
                               "max_stopouts_per_day": 2})
    cfg["logging"]["emit_entry_decisions"] = True
    state = _fresh_state()
    state["daily_stopout_count"] = 2
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("NEW")])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 0 and s["rejected"] == 1
    assert _decisions(tmp_path)[0]["reason"] == "max_stopouts_per_day"


def test_stopout_counters_maintained_by_closures(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "L-1": _closed_lot("AAA"), "L-2": _closed_lot("BBB"),
        "L-3": _closed_lot("CCC"),
    }}
    v2.close_position_v2("L-1", state, cfg, exit_price=9.2,
                         reason="stop_hit")
    v2.close_position_v2("L-2", state, cfg, exit_price=9.2,
                         reason="stop_hit")
    assert state["daily_stopout_count"] == 2
    assert state["consecutive_stopout_count"] == 2
    # A non-stop closure resets the streak but not the daily count.
    v2.close_position_v2("L-3", state, cfg, exit_price=11.5,
                         reason="target_hit")
    assert state["daily_stopout_count"] == 2
    assert state["consecutive_stopout_count"] == 0


def test_consecutive_stopouts_blocks_and_survives_rollover(tmp_path):
    cfg = _cfg(tmp_path, risk={
        "max_total_entries_per_day": 50, "max_gross_exposure_pct": 5.0,
        "stop_trading_after_consecutive_stopouts": 3})
    cfg["logging"]["emit_entry_decisions"] = True
    state = _fresh_state()
    state["consecutive_stopout_count"] = 3
    state["session_date"] = "2026-05-15"          # forces rollover
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("NEW")])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    # Rollover happened but the streak survives (v1 parity).
    assert state["consecutive_stopout_count"] == 3
    assert state["daily_stopout_count"] == 0      # daily count DID reset
    assert s["accepted"] == 0
    assert _decisions(tmp_path)[0]["reason"] == "consecutive_stopouts"


def _recovery_breaker_cfg(tmp_path, *, cooldown_sessions=0):
    cfg = _cfg(tmp_path, risk={
        "max_total_entries_per_day": 50,
        "max_gross_exposure_pct": 5.0,
        "max_stopouts_per_day": 3,
        "stop_trading_after_consecutive_stopouts": None,
        "stopout_breaker": {
            "enabled": True,
            "threshold": 3,
            "cooldown_sessions": cooldown_sessions,
            "probation_entries": 1,
            "probation_size_multiplier": 0.25,
        },
    })
    cfg["logging"]["emit_entry_decisions"] = True
    return cfg


def test_recovery_breaker_migrates_and_probation_allows_one_small_entry(
    tmp_path,
):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = _fresh_state()
    state["session_date"] = "2026-05-15"
    state["consecutive_stopout_count"] = 3
    _write(Path(cfg["paths"]["candidate_events_path"]), [
        _candidate("FIRST", rank=1),
        _candidate("SECOND", rank=2),
    ])

    summary = v2.consume_candidate_events(
        state,
        cfg,
        submit_supplier=_ok_submit,
        today_iso="2026-05-18",
        now_utc=_NOW,
    )

    assert summary["accepted"] == 1
    assert summary["rejected"] == 1
    breaker = state["stopout_breaker"]
    assert breaker["phase"] == "probation"
    assert breaker["tripped_session"] == "2026-05-15"
    assert breaker["probation_entries_used"] == 1
    pos = next(iter(state["open_positions"].values()))
    assert pos["symbol"] == "FIRST"
    assert pos["stopout_breaker_probation"] is True
    # Normal qty is 493 shares; final 25% probation sizing is 123.
    assert pos["qty"] == 123
    by_symbol = {d["symbol"]: d for d in _decisions(tmp_path)}
    assert by_symbol["SECOND"]["reason"] == (
        "stopout_breaker_probation_limit"
    )


def test_recovery_breaker_migration_after_legacy_midnight_roll_is_probation(
    tmp_path,
):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = _fresh_state()
    # The legacy process already reset today's daily count, but the
    # persistent stop streak came from a prior session.
    state["session_date"] = "2026-05-18"
    state["daily_stopout_count"] = 0
    state["consecutive_stopout_count"] = 3

    rolled = v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        "2026-05-18",
        cfg,
        is_trading_session=True,
    )

    assert rolled is False
    assert state["stopout_breaker"]["phase"] == "probation"
    assert state["stopout_breaker"]["cooldown_sessions_remaining"] == 0


def test_recovery_breaker_same_day_migration_with_stopouts_stays_tripped(
    tmp_path,
):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = _fresh_state()
    state["session_date"] = "2026-05-18"
    state["daily_stopout_count"] = 3
    state["consecutive_stopout_count"] = 3

    v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        "2026-05-18",
        cfg,
        is_trading_session=True,
    )

    assert state["stopout_breaker"]["phase"] == "tripped"


def test_recovery_breaker_probation_non_stop_closure_clears(tmp_path):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = {
        "session_date": "2026-05-18",
        "consecutive_stopout_count": 3,
        "daily_stopout_count": 0,
        "daily_realized_pnl_strategy": 0.0,
        "cumulative_realized_pnl_strategy": 0.0,
        "gross_exposure_dollars": 1000.0,
        "stopout_breaker": {
            "phase": "probation",
            "tripped_session": "2026-05-15",
            "cooldown_sessions_remaining": 0,
            "probation_entries_used": 1,
            "probation_link_ids": ["L-1"],
        },
        "open_positions": {
            "L-1": _closed_lot(
                "AAA", link_id="L-1", stopout_breaker_probation=True,
            ),
        },
    }

    v2.close_position_v2(
        "L-1", state, cfg, exit_price=11.5, reason="target_hit",
    )

    assert state["stopout_breaker"]["phase"] == "normal"
    assert state["consecutive_stopout_count"] == 0


def test_recovery_breaker_probation_stop_retrips(tmp_path):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = {
        "session_date": "2026-05-18",
        "consecutive_stopout_count": 3,
        "daily_stopout_count": 0,
        "daily_realized_pnl_strategy": 0.0,
        "cumulative_realized_pnl_strategy": 0.0,
        "gross_exposure_dollars": 1000.0,
        "stopout_breaker": {
            "phase": "probation",
            "tripped_session": "2026-05-15",
            "cooldown_sessions_remaining": 0,
            "probation_entries_used": 1,
            "probation_link_ids": ["L-1"],
        },
        "open_positions": {
            "L-1": _closed_lot(
                "AAA", link_id="L-1", stopout_breaker_probation=True,
            ),
        },
    }

    v2.close_position_v2(
        "L-1", state, cfg, exit_price=9.2, reason="stop_hit",
    )

    assert state["stopout_breaker"]["phase"] == "tripped"
    assert state["stopout_breaker"]["tripped_session"] == "2026-05-18"
    assert state["consecutive_stopout_count"] == 4


def test_recovery_breaker_can_skip_one_full_trading_session(tmp_path):
    cfg = _recovery_breaker_cfg(tmp_path, cooldown_sessions=1)
    state = _fresh_state()
    state["session_date"] = "2026-05-15"  # Friday
    state["consecutive_stopout_count"] = 3

    v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        "2026-05-18",
        cfg,
        is_trading_session=True,
    )
    assert state["stopout_breaker"]["phase"] == "cooldown"
    assert state["stopout_breaker"]["cooldown_sessions_remaining"] == 0

    v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        "2026-05-19",
        cfg,
        is_trading_session=True,
    )
    assert state["stopout_breaker"]["phase"] == "probation"


def test_recovery_breaker_does_not_consume_cooldown_on_closed_session(
    tmp_path,
):
    cfg = _recovery_breaker_cfg(tmp_path)
    state = _fresh_state()
    state["session_date"] = "2026-05-15"
    state["consecutive_stopout_count"] = 3

    v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc),
        "2026-05-16",
        cfg,
        is_trading_session=False,
    )
    assert state["stopout_breaker"]["phase"] == "tripped"

    v2.roll_session_if_needed(
        state,
        datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        "2026-05-18",
        cfg,
        is_trading_session=True,
    )
    assert state["stopout_breaker"]["phase"] == "probation"


# ---- sizing caps -----------------------------------------------------------


def test_max_per_trade_dollars_caps_notional():
    cfg = {"sizing": {
        "bankroll_fixed_dollars": 90000, "max_concurrent_positions": 18,
        "equal_slice_bankroll_fraction": 0.80, "min_order_notional": 500,
        "max_per_trade_dollars": 1000,
    }}
    qty, notional = v2.size_position({}, cfg, current_price=10.0)
    assert qty == 100                              # 1000 // 10, not 4000//10
    assert notional == pytest.approx(1000.0)


def test_target_risk_dollars_caps_qty():
    cfg = {"sizing": {
        "bankroll_fixed_dollars": 90000, "max_concurrent_positions": 18,
        "equal_slice_bankroll_fraction": 0.80, "min_order_notional": 500,
        "target_risk_dollars": 100.0,
    }}
    # slice = 4000 => uncapped qty 400; risk/share = 0.10*10 = 1.0
    # => risk cap 100 shares.
    qty, _ = v2.size_position({}, cfg, current_price=10.0, stop_pct=0.10)
    assert qty == 100
    # Without stop_pct the risk cap cannot apply.
    qty2, _ = v2.size_position({}, cfg, current_price=10.0)
    assert qty2 == 400


def test_probation_multiplier_applies_after_risk_and_minimum_notional():
    cfg = {"sizing": {
        "bankroll_fixed_dollars": 90000,
        "max_concurrent_positions": 13,
        "equal_slice_bankroll_fraction": 0.94,
        "min_order_notional": 500,
        "max_per_trade_dollars": 750,
        "target_risk_dollars": 123.5,
    }}
    qty, notional = v2.size_position(
        {}, cfg, current_price=10.0, stop_pct=0.1771,
        size_multiplier=0.25,
    )
    # Risk cap -> 69 normal shares; probation -> 17 shares. The final
    # $170 notional intentionally sits below the normal $500 minimum.
    assert qty == 17
    assert notional == pytest.approx(170.0)


# ---- strategy_slice_loss_pct -----------------------------------------------


def test_strategy_slice_loss_blocks_entries(tmp_path):
    cfg = _cfg(tmp_path, risk={
        "max_total_entries_per_day": 50, "max_gross_exposure_pct": 5.0,
        "strategy_slice_loss_pct": 0.025})
    cfg["logging"]["emit_entry_decisions"] = True
    state = _fresh_state()
    # slice = 90000/3 = 30000; -2.5% => -750. Book -800 realized.
    state["daily_realized_pnl_strategy"] = -800.0
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("NEW")])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 0
    assert _decisions(tmp_path)[0]["reason"] == "strategy_slice_loss"


def test_strategy_slice_loss_inactive_above_threshold(tmp_path):
    cfg = _cfg(tmp_path, risk={
        "max_total_entries_per_day": 50, "max_gross_exposure_pct": 5.0,
        "strategy_slice_loss_pct": 0.025})
    state = _fresh_state()
    state["daily_realized_pnl_strategy"] = -700.0  # above -750 trip
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("NEW")])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1


# ---- max_entries_per_scan ----------------------------------------------------


def test_max_entries_per_scan_caps_batch(tmp_path):
    cfg = _cfg(tmp_path, scanner={"max_entries_per_scan": 2})
    cfg["logging"]["emit_entry_decisions"] = True
    state = _fresh_state()
    same_scan = "2026-05-18T14:35:00Z"
    _write(Path(cfg["paths"]["candidate_events_path"]), [
        _candidate("AAA", rank=1, scan_ts=same_scan),
        _candidate("BBB", rank=2, scan_ts=same_scan),
        _candidate("CCC", rank=3, scan_ts=same_scan),
    ])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 2 and s["rejected"] == 1
    by_symbol = {d["symbol"]: d for d in _decisions(tmp_path)}
    assert by_symbol["AAA"]["decision"] == "accepted"
    assert by_symbol["BBB"]["decision"] == "accepted"
    assert by_symbol["CCC"]["reason"] == "max_entries_per_scan"


def test_max_entries_per_scan_takes_lowest_ranks(tmp_path):
    """Events written out of rank order still accept ranks 1..N."""
    cfg = _cfg(tmp_path, scanner={"max_entries_per_scan": 1})
    cfg["logging"]["emit_entry_decisions"] = True
    state = _fresh_state()
    same_scan = "2026-05-18T14:35:00Z"
    _write(Path(cfg["paths"]["candidate_events_path"]), [
        _candidate("WORSE", rank=2, scan_ts=same_scan),
        _candidate("BEST", rank=1, scan_ts=same_scan),
    ])
    v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    by_symbol = {d["symbol"]: d for d in _decisions(tmp_path)}
    assert by_symbol["BEST"]["decision"] == "accepted"
    assert by_symbol["WORSE"]["reason"] == "max_entries_per_scan"


def test_separate_scans_get_separate_budgets(tmp_path):
    cfg = _cfg(tmp_path, scanner={"max_entries_per_scan": 1})
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]), [
        _candidate("AAA", rank=1, scan_ts="2026-05-18T14:35:00Z"),
        _candidate("BBB", rank=1, scan_ts="2026-05-18T14:40:00Z"),
    ])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 2


# ---- same_symbol_entries_per_day ---------------------------------------------


def test_same_symbol_entries_per_day_generalized():
    state = {"entered_today": ["AAA"]}
    cfg1 = {"scanner": {"same_symbol_entries_per_day": 1}}
    cfg2 = {"scanner": {"same_symbol_entries_per_day": 2}}
    assert v2._symbol_already_entered_today(state, "AAA", cfg1) is True
    assert v2._symbol_already_entered_today(state, "AAA", cfg2) is False
    state2 = {"entered_today": ["AAA", "AAA"]}
    assert v2._symbol_already_entered_today(state2, "AAA", cfg2) is True
    # Default (no cfg) stays 1-per-day.
    assert v2._symbol_already_entered_today(state, "AAA") is True
    assert v2._symbol_already_entered_today(state, "BBB") is False


# ---- symbol_cooldown_minutes ---------------------------------------------------


def test_stopout_writes_cooldown_and_entry_rejected(tmp_path):
    cfg = _cfg(tmp_path, scanner={"symbol_cooldown_minutes": 390})
    cfg["logging"]["emit_entry_decisions"] = True
    state = {"open_positions": {"L-1": _closed_lot("AAA")},
             "entered_today": [], "daily_entries_count": 0,
             "last_consumed_event_offset": 0,
             "gross_exposure_dollars": 1000.0}
    v2.close_position_v2("L-1", state, cfg, exit_price=9.2,
                         reason="stop_hit")
    assert "AAA" in state.get("cooldowns", {})

    # The cooldown is stamped at wall-clock now; consume at wall-clock
    # now with a candidate whose session/expiry accommodate it.
    ev = _candidate("AAA")
    ev["session_date"] = "2099-01-01"
    ev["signal_expiry_timestamp"] = "2099-01-01T23:59:59Z"
    _write(Path(cfg["paths"]["candidate_events_path"]), [ev])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2099-01-01",
        now_utc=datetime.now(timezone.utc),
    )
    assert s["accepted"] == 0
    reasons = [d["reason"] for d in _decisions(tmp_path)]
    assert "symbol_cooldown" in reasons


def test_expired_cooldown_purged_on_rollover(tmp_path):
    cfg = _cfg(tmp_path)
    Path(cfg["paths"]["candidate_events_path"]).write_text("")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    state = {
        "session_date": "2026-05-15", "entered_today": [],
        "daily_entries_count": 0, "last_consumed_event_offset": 0,
        "open_positions": {},
        "cooldowns": {"OLD": {"until": past},
                      "HOT": {"until": future}},
    }
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-18",
        now_utc=datetime.now(timezone.utc),
    )
    assert "OLD" not in state["cooldowns"]
    assert "HOT" in state["cooldowns"]


# ---- fresh_bar_gate (scanner) ---------------------------------------------------


def test_fresh_bar_gate_helper():
    import bowaka_intraday_scanner as scanner
    scan = datetime(2026, 5, 18, 18, 36, tzinfo=timezone.utc)
    # Bar started 18:34 -> ended 18:35 -> 60s stale at 18:36: passes 90s.
    assert scanner._fresh_bar_ok("2026-05-18T18:34:00Z", scan, 90) is True
    # Bar started 18:30 -> ended 18:31 -> 300s stale: fails.
    assert scanner._fresh_bar_ok("2026-05-18T18:30:00Z", scan, 90) is False
    # Missing / garbage timestamps fail closed.
    assert scanner._fresh_bar_ok(None, scan, 90) is False
    assert scanner._fresh_bar_ok("not-a-ts", scan, 90) is False


def test_fresh_bar_gate_in_scan_and_gate_dump(tmp_path, monkeypatch):
    import pandas as pd

    import bowaka_intraday_scanner as scanner
    import bowaka_v2_paths as p
    dump_path = tmp_path / "gate_dump.jsonl"
    monkeypatch.setattr(p, "SCANNER_GATE_DUMP_PATH", dump_path)

    scan_ts = datetime(2026, 5, 18, 18, 40, tzinfo=timezone.utc)
    stale_bars = pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-05-18T18:00:00Z")],
        "open": [8.0], "high": [8.2], "low": [7.9], "close": [8.1],
        "volume": [50000],
    })
    cfg = {
        "scanner": {"require_fresh_intraday_bar": True,
                    "debug_gate_dump": True,
                    "max_candidates_per_scan": 5},
        "data": {"max_bar_age_seconds": 90},
        "signals": {}, "score": {}, "historical_features": {},
        "session": {},
    }
    universe = {"universe_hash": "sha256:t", "symbols": [
        {"symbol": "AAA", "instrument_class": "operating_equity"},
    ]}
    daily_cache = pd.DataFrame([{
        "symbol": "AAA", "prior_close": 7.42, "avg_volume_20d": 450000,
        "avg_dollar_volume_20d": 3_000_000, "prior_atr_14d": 0.52,
        "prior_atr_pct": 0.0701, "ema_10_prior": 7.18,
        "ema_10_lag_3": 7.04, "ema_slope_prior": 0.0199,
    }])
    emitted = scanner.evaluate_one_scan(
        cfg=cfg, universe_snapshot=universe, daily_cache=daily_cache,
        volume_curve=None, state={}, scan_ts=scan_ts,
        bars_supplier=lambda sym, ts: stale_bars,
        candidate_events_path=tmp_path / "cand.jsonl",
        heartbeat_path=tmp_path / "hb.jsonl",
    )
    assert emitted == []                          # stale bar blocked it
    rows = [json.loads(l) for l in dump_path.read_text().splitlines()]
    row = next(r for r in rows if r.get("symbol") == "AAA")
    assert row["gate_results"]["fresh_bar_gate"] is False
    assert "fresh_bar_gate" in row["failing_gates"]


# ---- protected position: attach attempts + fallback stop ---------------------


class _FakeOAProtect:
    def __init__(self):
        self.cancel_calls = []
        self.market_sells = []
        self.stop_sells = []

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        return {"status": "canceled", "order_id": order_id}

    def submit_market_sell(self, http, api_key, **kw):
        self.market_sells.append(kw)
        return {"data": {"order_id": "EXIT-1"}, "_http_status": 200}

    def submit_stop_sell(self, http, api_key, **kw):
        self.stop_sells.append(kw)
        return {"data": {"order_id": "FBSTOP-1"}, "_http_status": 200}


def _pp_cfg(tmp_path, **pp_over):
    cfg = _cfg(tmp_path)
    cfg["protected_position"] = {
        "enabled": True, "max_unprotected_seconds": 3600,
        "max_oco_attach_attempts": 2,
        "flatten_if_unprotected": True,
        "fallback_stop_enabled": False,
    }
    cfg["protected_position"].update(pp_over)
    cfg["logging"]["log_protection_state"] = True
    return cfg


def _unbracketed(symbol="AAA", attempts=2):
    return {
        "symbol": symbol, "qty": 100, "status": "filled",
        "entry_price": 10.0, "link_id": f"L-{symbol}",
        "entry_timestamp": datetime.now(timezone.utc).isoformat(),
        "child_order_ids": {"target": "", "stop": ""},
        "oco_attach_attempts": attempts, "stop_pct": 0.08,
        "venue_code": "XNAS",
    }


def test_exhausted_attach_attempts_flatten_immediately(tmp_path):
    """max_unprotected_seconds has NOT elapsed, but attempts are
    exhausted — flatten fires immediately."""
    cfg = _pp_cfg(tmp_path)
    state = {"open_positions": {"L-1": _unbracketed(attempts=2)}}
    oa = _FakeOAProtect()
    out = v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == ["AAA"]
    assert len(oa.market_sells) == 1
    assert state["open_positions"]["L-1"]["exit_reason"] == (
        "protected_position_flatten")


def test_attempts_below_max_wait_for_age(tmp_path):
    cfg = _pp_cfg(tmp_path)
    state = {"open_positions": {"L-1": _unbracketed(attempts=1)}}
    oa = _FakeOAProtect()
    out = v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == []                              # age (3600s) not reached
    assert oa.market_sells == []


def test_fallback_stop_attached_when_flatten_disabled(tmp_path):
    cfg = _pp_cfg(tmp_path, flatten_if_unprotected=False,
                  fallback_stop_enabled=True)
    pos = _unbracketed(attempts=2)
    state = {"open_positions": {"L-1": pos}}
    oa = _FakeOAProtect()
    out = v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == []
    assert len(oa.stop_sells) == 1
    assert oa.stop_sells[0]["trigger_price"] == pytest.approx(9.20)
    assert pos["child_order_ids"]["stop"] == "FBSTOP-1"
    assert pos["fallback_stop_attached"] is True
    ledger = [json.loads(l) for l in
              (tmp_path / "trade_ledger.jsonl").read_text().splitlines()]
    assert any(e["event_type"] == "fallback_stop_attached"
               for e in ledger)
    # Second pass must not attach a second stop.
    v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert len(oa.stop_sells) == 1


# ---- feature snapshots -----------------------------------------------------


def test_feature_snapshot_written_on_entry(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["logging"]["emit_feature_snapshots"] = True
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    assert s["accepted"] == 1
    import bowaka_v2_paths as p
    rows = [json.loads(l) for l in
            p.FEATURE_SNAPSHOTS_PATH.read_text().splitlines()]
    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["features"]["signal_strength"] == 7.82
    assert rows[0]["prior_daily_baselines"]["prior_close"] == 7.42


def test_feature_snapshot_off_by_default(tmp_path):
    cfg = _cfg(tmp_path)                          # key absent
    state = _fresh_state()
    _write(Path(cfg["paths"]["candidate_events_path"]),
           [_candidate("AAA")])
    v2.consume_candidate_events(
        state, cfg, submit_supplier=_ok_submit,
        today_iso="2026-05-18", now_utc=_NOW,
    )
    import bowaka_v2_paths as p
    assert not p.FEATURE_SNAPSHOTS_PATH.exists()


# ---- strict config validator -------------------------------------------------


def _shipped_config() -> dict:
    root = Path(__file__).resolve().parents[2]
    return yaml.safe_load(
        (root / "strategies" / "scripts" / "bowaka_v2_config.yaml")
        .read_text(encoding="utf-8"),
    )


def test_validator_accepts_shipped_config():
    config_schema.validate_config(_shipped_config())


def test_validator_rejects_misspelled_key():
    cfg = _shipped_config()
    cfg["risk"]["max_stopouts_per_dya"] = 7        # typo
    with pytest.raises(config_schema.ConfigError) as exc:
        config_schema.validate_config(cfg)
    assert "risk.max_stopouts_per_dya" in str(exc.value)


def test_validator_rejects_unknown_top_level():
    with pytest.raises(config_schema.ConfigError):
        config_schema.validate_config({"riskk": {"x": 1}})


def test_validator_allows_known_but_null():
    config_schema.validate_config({"risk": None, "sizing": {
        "max_per_trade_dollars": None}})


def test_validator_escape_hatch(monkeypatch):
    monkeypatch.setenv("BOWAKA_CONFIG_ALLOW_UNKNOWN", "1")
    config_schema.validate_config({"riskk": {"x": 1}})  # warns, no raise


def test_validator_checks_list_of_dicts():
    cfg = {"risk": {"adv_tier_caps": [
        {"max_adv_dollars": 1, "reject_if_below": True},
        {"max_adv_dollarz": 2},                    # typo inside list
    ]}}
    unknown = config_schema.find_unknown_keys(cfg)
    assert unknown == ["risk.adv_tier_caps[1].max_adv_dollarz"]
