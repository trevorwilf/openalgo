"""Compounding sizing bankroll (2026-06-09): grow/shrink on cumulative
realized PnL, with a floor (halt new entries at <=0.50x base) and a cap
(size off min(equity, 4x base); profit beyond stays in the account).

Risk controls (daily_loss, gross/ADV caps) stay anchored to the BASE, not
the compounded bankroll — verified here. Exercises the real functions in
bowaka_v2_strategy with realistic state/config fixtures.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bowaka_v2_strategy as v2


# ---------- fixtures ----------


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "V2_LEDGER_PATH", tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                        tmp_path / "daily_summary.jsonl")
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                        tmp_path / "protection_events.jsonl")
    # Reset the once-per-process floor-halt warning guard between tests.
    v2._FLOOR_HALT_WARNED["v"] = False


def _sizing_cfg(*, enabled=True, base=90000, floor=0.50, cap=4.0,
                base_override=None):
    return {
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": base,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
            "compounding": {
                "enabled": enabled,
                "base_dollars": base_override,
                "floor_fraction": floor,
                "cap_multiple": cap,
            },
        },
        "risk": {
            "max_total_entries_per_day": 10,
            "max_gross_exposure_pct": 0.80,
            "daily_loss_pct": 0.03,
        },
    }


def _ledger_cfg(tmp_path, **kw):
    cfg = _sizing_cfg(**kw)
    cfg["paths"] = {
        "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
        "state_path": str(tmp_path / "state.json"),
    }
    cfg["execution"] = {"default_venue_code": "XNAS"}
    cfg["exits"] = {"stop_pct": 0.025, "target_pct": 0.15, "max_hold_days": 3}
    return cfg


def _open_lot(symbol="AAA", qty=100, entry=10.0, link="L-1"):
    return {
        "symbol": symbol, "qty": qty, "venue_code": "XNAS",
        "entry_price": entry, "status": "filled",
        "entry_timestamp": "2026-05-15T13:30:00Z", "link_id": link,
        "target_pct": 0.15, "stop_pct": 0.025,
        "target_price": entry * 1.15, "stop_price": entry * 0.975,
        "peak_since_entry": entry, "trough_since_entry": entry,
    }


# ---------- size_position: scale / cap / disabled ----------


def test_size_position_legacy_when_disabled():
    cfg = _sizing_cfg(enabled=False)
    state = {"cumulative_realized_pnl_strategy": 999_999.0}  # ignored
    qty, notional = v2.size_position(
        {"symbol": "AAA"}, cfg, current_price=10.0, state=state)
    assert notional == pytest.approx(0.80 * 90000 / 18)  # 4000
    assert qty == 400


def test_size_position_scales_up_between_floor_and_cap():
    cfg = _sizing_cfg(enabled=True)
    state = {"cumulative_realized_pnl_strategy": 90_000.0}  # effective 180k
    qty, notional = v2.size_position(
        {"symbol": "AAA"}, cfg, current_price=10.0, state=state)
    assert notional == pytest.approx(0.80 * 180000 / 18)  # 8000


def test_size_position_clamps_at_cap():
    cfg = _sizing_cfg(enabled=True)
    state = {"cumulative_realized_pnl_strategy": 500_000.0}  # effective 590k
    qty, notional = v2.size_position(
        {"symbol": "AAA"}, cfg, current_price=10.0, state=state)
    # capped at 4x base = 360k, NOT 590k
    assert notional == pytest.approx(0.80 * 360000 / 18)  # 16000


def test_sizing_cap_edge_is_clamped_inclusive():
    cfg = _sizing_cfg(enabled=True)  # cap = 4 * 90000 = 360000
    at = {"cumulative_realized_pnl_strategy": 270_000.0}    # effective == 360k
    over = {"cumulative_realized_pnl_strategy": 270_001.0}  # just over cap
    assert v2._sizing_bankroll(at, cfg) == pytest.approx(360000.0)
    assert v2._sizing_bankroll(over, cfg) == pytest.approx(360000.0)


def test_size_position_scales_down_above_floor():
    cfg = _sizing_cfg(enabled=True)
    state = {"cumulative_realized_pnl_strategy": -20_000.0}  # effective 70k
    qty, notional = v2.size_position(
        {"symbol": "AAA"}, cfg, current_price=10.0, state=state)
    # size_position returns (qty, qty*price): target 3111.11 // 10 -> 311.
    assert qty == 311
    assert notional == pytest.approx(3110.0)


def test_size_position_base_dollars_override():
    cfg = _sizing_cfg(enabled=True, base=90000, base_override=50000)
    assert v2._compounding_base(cfg) == pytest.approx(50000.0)
    # cap at 4*50000=200000, floor at 0.5*50000=25000
    state = {"cumulative_realized_pnl_strategy": 1_000_000.0}
    assert v2._sizing_bankroll(state, cfg) == pytest.approx(200000.0)
    assert v2._below_floor({"cumulative_realized_pnl_strategy": -25001.0}, cfg)
    assert not v2._below_floor(
        {"cumulative_realized_pnl_strategy": -24999.0}, cfg)


# ---------- floor boundary + _risk_gates halt ----------


def test_below_floor_boundary_is_inclusive():
    cfg = _sizing_cfg(enabled=True)
    assert v2._below_floor({"cumulative_realized_pnl_strategy": -45000.0}, cfg)
    assert v2._below_floor({"cumulative_realized_pnl_strategy": -45001.0}, cfg)
    assert not v2._below_floor(
        {"cumulative_realized_pnl_strategy": -44999.0}, cfg)


def test_risk_gate_floor_halt_at_and_below():
    cfg = _sizing_cfg(enabled=True)
    ev = {"symbol": "AAA"}
    base_state = {"open_positions": {}, "daily_entries_count": 0,
                  "gross_exposure_dollars": 0.0}
    at = {**base_state, "cumulative_realized_pnl_strategy": -45000.0}
    below = {**base_state, "cumulative_realized_pnl_strategy": -45001.0}
    above = {**base_state, "cumulative_realized_pnl_strategy": -44999.0}
    assert v2._risk_gates(ev, at, cfg, candidate_adv=None,
                          target_notional=4000) == "bankroll_floor_halt"
    assert v2._risk_gates(ev, below, cfg, candidate_adv=None,
                          target_notional=4000) == "bankroll_floor_halt"
    assert v2._risk_gates(ev, above, cfg, candidate_adv=None,
                          target_notional=4000) is None


def test_risk_gate_no_floor_when_disabled():
    cfg = _sizing_cfg(enabled=False)
    state = {"open_positions": {}, "daily_entries_count": 0,
             "gross_exposure_dollars": 0.0,
             "cumulative_realized_pnl_strategy": -80_000.0}
    assert v2._risk_gates({"symbol": "AAA"}, state, cfg,
                          candidate_adv=None, target_notional=4000) is None


def test_cap_does_not_block_entry():
    cfg = _sizing_cfg(enabled=True)
    state = {"open_positions": {}, "daily_entries_count": 0,
             "gross_exposure_dollars": 0.0,
             "cumulative_realized_pnl_strategy": 500_000.0}
    assert v2._risk_gates({"symbol": "AAA"}, state, cfg,
                          candidate_adv=None, target_notional=4000) is None


def test_floor_halt_wins_over_other_gates():
    """Floor is checked first: below-floor returns the floor reason even
    when max_concurrent / daily cap would also block."""
    cfg = _sizing_cfg(enabled=True)
    state = {
        "open_positions": {f"L-{i}": {} for i in range(18)},  # at max
        "daily_entries_count": 99,                            # over cap
        "gross_exposure_dollars": 0.0,
        "cumulative_realized_pnl_strategy": -60_000.0,        # below floor
    }
    assert v2._risk_gates({"symbol": "AAA"}, state, cfg,
                          candidate_adv=None,
                          target_notional=4000) == "bankroll_floor_halt"


def test_risk_controls_anchored_to_base_not_compounded():
    """gross/daily-loss denominators must stay at the base ($90k), NOT
    the compounded bankroll — the hook is deliberately not populated."""
    cfg = _sizing_cfg(enabled=True)
    # huge cumulative; if gross used the compounded bankroll (360k) this
    # would pass, but anchored to 90k base it must trip at 0.80*90k=72k.
    state = {"open_positions": {}, "daily_entries_count": 0,
             "gross_exposure_dollars": 70_000.0,
             "cumulative_realized_pnl_strategy": 270_000.0}
    assert v2._risk_gates({"symbol": "AAA"}, state, cfg, candidate_adv=None,
                          target_notional=5000) == "gross_exposure_cap"


# ---------- closure accumulator ----------


def test_closure_accumulates_cumulative_realized(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    state = {"open_positions": {"L-1": _open_lot()},
             "gross_exposure_dollars": 1000.0,
             "cumulative_realized_pnl_strategy": 0.0}
    rec = v2.close_position_v2("L-1", state, cfg,
                               exit_price=11.0, reason="target_hit")
    assert rec is not None and rec["realized_pnl"] == pytest.approx(100.0)
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(100.0)


def test_no_double_count_on_reclose(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    state = {"open_positions": {"L-1": _open_lot()},
             "gross_exposure_dollars": 1000.0,
             "cumulative_realized_pnl_strategy": 0.0}
    first = v2.close_position_v2("L-1", state, cfg,
                                 exit_price=11.0, reason="target_hit")
    assert first is not None
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(100.0)
    second = v2.close_position_v2("L-1", state, cfg,
                                  exit_price=11.0, reason="target_hit")
    assert second is None
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(100.0)
    # ledger must hold exactly one closure -> reconcile reads 100, not 200.
    assert v2._ledger_realized_sum(cfg) == pytest.approx(100.0)


# ---------- ledger reconciliation ----------


def test_ledger_realized_sum(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    p = Path(cfg["paths"]["daily_summary_path"])
    p.write_text(
        json.dumps({"record_type": "closure", "realized_pnl": 100.0}) + "\n"
        + json.dumps({"record_type": "closure", "realized_pnl": -40.0}) + "\n"
        + json.dumps({"record_type": "other", "realized_pnl": 999.0}) + "\n"
        + "{ not valid json\n"
        + json.dumps({"record_type": "closure", "realized_pnl": 25.5}) + "\n",
        encoding="utf-8",
    )
    assert v2._ledger_realized_sum(cfg) == pytest.approx(85.5)


def test_ledger_realized_sum_missing_file_is_zero(tmp_path):
    cfg = _ledger_cfg(tmp_path)  # file does not exist yet
    assert v2._ledger_realized_sum(cfg) == 0.0


def test_ledger_sum_excludes_bool_realized_pnl(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    Path(cfg["paths"]["daily_summary_path"]).write_text(
        json.dumps({"record_type": "closure", "realized_pnl": True}) + "\n"
        + json.dumps({"record_type": "closure", "realized_pnl": 40.0}) + "\n",
        encoding="utf-8")
    assert v2._ledger_realized_sum(cfg) == pytest.approx(40.0)  # not 41.0


# ---------- main() ledger reconciliation (authoritative overwrite) ----------


def test_reconcile_overwrites_stale_state_from_ledger(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    Path(cfg["paths"]["daily_summary_path"]).write_text(
        json.dumps({"record_type": "closure", "realized_pnl": 200.0}) + "\n"
        + json.dumps({"record_type": "closure", "realized_pnl": 50.0}) + "\n",
        encoding="utf-8")
    # state carries a WRONG/stale value; reconcile must OVERWRITE (not +=).
    state = {"cumulative_realized_pnl_strategy": 99_999.0}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(250.0)


def test_reconcile_seeds_legacy_state_from_ledger(tmp_path):
    cfg = _ledger_cfg(tmp_path)
    Path(cfg["paths"]["daily_summary_path"]).write_text(
        json.dumps({"record_type": "closure", "realized_pnl": 130.0}) + "\n",
        encoding="utf-8")
    state = {}  # legacy: no cumulative field at all
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(130.0)


def test_reconcile_missing_ledger_keeps_nonzero_cumulative(tmp_path):
    """Fix Phase 7 (deliberate behavior change): a MISSING ledger with
    a nonzero in-state cumulative is treated as ledger-lost — the
    in-state value is KEPT (operator triage) instead of silently
    zeroing the compounding bankroll."""
    cfg = _ledger_cfg(tmp_path)  # no ledger file
    state = {"cumulative_realized_pnl_strategy": 500.0}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == 500.0


def test_reconcile_empty_existing_ledger_zeroes_cumulative(tmp_path):
    """An EXISTING ledger with no closure rows is authoritative: the
    lifetime sum really is 0.0."""
    cfg = _ledger_cfg(tmp_path)
    (tmp_path / "daily_summary.jsonl").write_text("", encoding="utf-8")
    state = {"cumulative_realized_pnl_strategy": 500.0}
    v2._reconcile_cumulative_from_ledger(state, cfg)
    assert state["cumulative_realized_pnl_strategy"] == 0.0


# ---------- restart safety ----------


def test_restart_roundtrip_reconstructs_bankroll(tmp_path):
    cfg = _sizing_cfg(enabled=True)
    state = {"cumulative_realized_pnl_strategy": 90_000.0,
             "open_positions": {}}
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps(state), encoding="utf-8")
    reloaded = json.loads(sp.read_text(encoding="utf-8"))
    assert v2._sizing_bankroll(reloaded, cfg) == pytest.approx(180000.0)


def test_legacy_state_without_field_uses_base(tmp_path):
    cfg = _sizing_cfg(enabled=True)
    legacy = {}  # no cumulative key
    assert v2._sizing_bankroll(legacy, cfg) == pytest.approx(90000.0)
    assert v2._effective_equity(legacy, cfg) == pytest.approx(90000.0)
    assert not v2._below_floor(legacy, cfg)


# ---------- consume integration ----------


def _make_candidate(symbol: str, session="2026-05-18") -> dict:
    import bowaka_v2_schemas as schemas
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2", "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:{session}:{symbol}:scan",
        "generated_at": f"{session}T14:35:00Z", "session_date": session,
        "scan_timestamp": f"{session}T14:35:00Z",
        "provider": "alpaca", "data_feed": "sip", "bar_interval": "1m",
        "config_hash": "sha256:t", "universe_hash": "sha256:t",
        "symbol": symbol, "exchange": "NASDAQ", "venue_code": "XNAS",
        "instrument_class": "operating_equity",
        "eligible_for_bowaka_equity_bucket": True,
        "prior_daily_baselines": {
            "prior_close": 7.42, "avg_volume_20d": 450000,
            "avg_dollar_volume_20d": 3_000_000, "prior_atr_14d": 0.52,
            "prior_atr_pct": 0.0701, "ema_10_prior": 7.18,
            "ema_10_lag_3": 7.04, "ema_slope_prior": 0.0199,
        },
        "forming_session_bar": {
            "session_open": 7.61, "session_high": 8.20, "session_low": 7.50,
            "last_price": 8.11, "session_volume": 820000,
            "session_range": 0.70, "last_bar_timestamp": f"{session}T18:34:00Z",
        },
        "intraday_volume_context": {
            "volume_curve_fraction": 0.42,
            "expected_volume_until_scan": 189000,
            "rvol_so_far": 4.34, "projected_full_day_rvol": 4.34,
        },
        "features": {
            "gap_pct": 0.0256, "current_return_pct": 0.1482,
            "range_expansion_so_far": 1.346, "close_location_so_far": 0.871,
            "ema_distance": 0.128, "ema_slope": 0.0199, "signal_strength": 7.82,
        },
        "gate_results": {
            "price_gate": True, "avg_dollar_volume_gate": True,
            "rvol_gate": True, "prior_atr_pct_gate": True,
            "range_expansion_gate": True, "close_location_gate": True,
            "ema_distance_gate": True, "ema_slope_gate": True,
            "max_gap_gate": True, "instrument_gate": True,
        },
        "candidate_rank": 1,
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }


def _consume_cfg(tmp_path, cand_path, *, enabled=True):
    cfg = _ledger_cfg(tmp_path, enabled=enabled)
    cfg["paths"]["candidate_events_path"] = str(cand_path)
    cfg["strategy"] = {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"}
    cfg["data"] = {"feed": "sip", "allow_non_sip_for_research_only": False}
    cfg["execution"] = {
        "default_venue_code": "XNAS",
        "quote_gate": {"enabled": False},
        "price_chase_gate": {"enabled": False},
        "halt_gate": {"enabled": False},
    }
    cfg["logging"] = {k: False for k in (
        "emit_entry_decisions", "emit_rejected_candidates",
        "log_order_execution_quality", "log_protection_state",
        "log_shadow_risk_controls", "log_counterfactual_entries",
        "log_counterfactual_exits",
    )}
    return cfg


def test_no_daily_reset_of_cumulative(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text("")
    cfg = _consume_cfg(tmp_path, cand, enabled=True)
    state = {
        "session_date": "2026-05-18", "entered_today": ["AAA"],
        "daily_entries_count": 5, "daily_realized_pnl_strategy": -123.45,
        "gross_exposure_dollars": 30000.0, "last_consumed_event_offset": 0,
        "open_positions": {}, "cumulative_realized_pnl_strategy": 50_000.0,
    }
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-19",
        now_utc=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc))
    # daily counters reset...
    assert state["daily_entries_count"] == 0
    assert state["daily_realized_pnl_strategy"] == 0.0
    # ...but the lifetime cumulative survives rollover.
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(50_000.0)


def test_consumer_sizes_off_compounded_bankroll(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = _consume_cfg(tmp_path, cand, enabled=True)
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {},
             "session_date": "2026-05-18",
             "cumulative_realized_pnl_strategy": 90_000.0}  # effective 180k

    submitted = {}

    def fake_submit(symbol, qty):
        submitted["qty"] = qty
        return {"_http_status": 200, "data": {"order_id": f"P-{symbol}"}}

    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=fake_submit, today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc))
    assert s["accepted"] == 1
    pos = v2.lots_for_symbol(state, "AAA")[0]
    # compounded target = 0.80*180000/18 = 8000; qty = 8000 // 8.11
    assert pos["qty"] == int((0.80 * 180000 / 18) // 8.11)


def test_floor_halt_blocks_new_entries_but_allows_exits(tmp_path):
    cand = tmp_path / "candidates.jsonl"
    cand.write_text(json.dumps(_make_candidate("BBB")) + "\n")
    cfg = _consume_cfg(tmp_path, cand, enabled=True)
    state = {
        "last_consumed_event_offset": 0, "entered_today": [],
        "daily_entries_count": 0, "session_date": "2026-05-18",
        "gross_exposure_dollars": 1000.0,
        "open_positions": {"L-1": _open_lot(symbol="AAA")},
        "cumulative_realized_pnl_strategy": -50_000.0,  # effective 40k < 45k
    }
    s = v2.consume_candidate_events(
        state, cfg, submit_supplier=lambda sym, qty: {"_http_status": 200},
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc))
    # NEW entry refused while below floor.
    assert s["accepted"] == 0
    assert v2.lots_for_symbol(state, "BBB") == []
    # ...but the existing lot can still be exited.
    closures = v2.process_fill_events_v2([{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "T-1",
        "role": "target", "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": 11.0, "raw": {},
    }], state, cfg)
    assert len(closures) == 1
    assert "L-1" not in state["open_positions"]
