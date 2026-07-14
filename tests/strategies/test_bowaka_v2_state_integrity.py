"""Hardening Phase 3 — state & accounting integrity.

Covers:
- state recovery: corrupt state.json falls back to .tmp, then the
  newest .bak_*; unrecoverable state is flagged,
- broker-truth reconciliation: orphan broker positions halt (exit 7)
  under halt_on_orphans, state lots missing at the broker are marked
  broker_missing, unrecoverable state + broker positions always halt,
- rollover recomputes gross exposure from open lots (never zeroes
  under live positions),
- exposure symmetry: entry -> fill at a different price -> close
  leaves gross_exposure_dollars at exactly 0,
- daily state backups with keep-5 pruning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bowaka_v2_schemas as schemas
import bowaka_v2_strategy as v2


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                        tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                        tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                        tmp_path / "daily_summary.jsonl")
    monkeypatch.setattr(p, "ENTRY_DECISIONS_PATH",
                        tmp_path / "entry_decisions.jsonl")
    monkeypatch.setattr(p, "REJECTED_CANDIDATES_PATH",
                        tmp_path / "rejected_candidates.jsonl")


def _cfg(tmp_path, **over):
    cfg = {
        "paths": {
            "candidate_events_path": str(tmp_path / "candidates.jsonl"),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS",
                      "quote_gate": {"enabled": False},
                      "price_chase_gate": {"enabled": False},
                      "halt_gate": {"enabled": False}},
        "sizing": {
            "sizing_mode": "equal_slice",
            "bankroll_fixed_dollars": 90000,
            "max_concurrent_positions": 18,
            "equal_slice_bankroll_fraction": 0.80,
            "min_order_notional": 500,
        },
        "risk": {"max_total_entries_per_day": 10,
                 "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                  "max_hold_days": 3},
        "reconcile": {"halt_on_orphans": True},
        "logging": {k: False for k in (
            "emit_entry_decisions", "emit_rejected_candidates",
            "log_order_execution_quality", "log_protection_state",
            "log_shadow_risk_controls", "log_counterfactual_entries",
            "log_counterfactual_exits",
        )},
    }
    cfg.update(over)
    return cfg


# ---- state recovery -----------------------------------------------------


def test_recovery_prefers_primary(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"marker": "primary"}))
    state, failed = v2.load_state_with_recovery(sp)
    assert state["marker"] == "primary" and failed is False


def test_recovery_falls_back_to_tmp(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text("{corrupt json !!!")
    (tmp_path / "state.json.tmp").write_text(
        json.dumps({"marker": "tmp"}))
    state, failed = v2.load_state_with_recovery(sp)
    assert state["marker"] == "tmp" and failed is False


def test_recovery_falls_back_to_newest_bak(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text("{corrupt json !!!")
    (tmp_path / "state.json.bak_20260710").write_text(
        json.dumps({"marker": "old"}))
    (tmp_path / "state.json.bak_20260713").write_text(
        json.dumps({"marker": "newest"}))
    state, failed = v2.load_state_with_recovery(sp)
    assert state["marker"] == "newest" and failed is False


def test_recovery_flags_total_failure(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text("{corrupt json !!!")
    (tmp_path / "state.json.bak_20260713").write_text("also corrupt {")
    state, failed = v2.load_state_with_recovery(sp)
    assert state == {} and failed is True


def test_recovery_missing_file_is_clean_start(tmp_path):
    state, failed = v2.load_state_with_recovery(tmp_path / "state.json")
    assert state == {} and failed is False


# ---- broker reconciliation ----------------------------------------------


class _FakeOA:
    def __init__(self, positions=None, orders=None):
        self.positions = positions or []
        self.orders = orders or []

    def fetch_positions(self, http, api_key):
        return list(self.positions)

    def fetch_all_orders(self, http, api_key):
        return list(self.orders)


def _lot(symbol, status="filled", **over):
    pos = {
        "symbol": symbol, "qty": 100, "status": status,
        "entry_price": 10.0, "link_id": f"L-{symbol}",
        "recorded_exposure": 1000.0,
    }
    pos.update(over)
    return pos


def test_orphan_position_halts_with_exit_7(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["logging"]["log_protection_state"] = True
    state = {"open_positions": {}}
    oa = _FakeOA(positions=[{"symbol": "GHOST", "qty": 50}])
    rc = v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert rc == 7
    events = [json.loads(l) for l in
              (tmp_path / "protection_events.jsonl")
              .read_text().splitlines()]
    orphaned = [e for e in events
                if e["event"] == "orphan_position_detected"]
    assert orphaned and orphaned[0]["symbol"] == "GHOST"


def test_orphan_with_halt_disabled_continues(tmp_path):
    cfg = _cfg(tmp_path, reconcile={"halt_on_orphans": False})
    cfg["logging"]["log_protection_state"] = True
    state = {"open_positions": {}}
    oa = _FakeOA(positions=[{"symbol": "GHOST", "qty": 50}])
    rc = v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert rc is None


def test_matching_positions_pass_clean(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-AAA": _lot("AAA")}}
    oa = _FakeOA(positions=[{"symbol": "AAA", "qty": 100}])
    rc = v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert rc is None
    assert "broker_missing" not in state["open_positions"]["L-AAA"]


def test_state_lot_missing_at_broker_marked_not_dropped(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-AAA": _lot("AAA")}}
    oa = _FakeOA(positions=[])
    rc = v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert rc is None
    assert state["open_positions"]["L-AAA"]["broker_missing"] is True
    assert "L-AAA" in state["open_positions"]     # never auto-deleted


def test_pending_fill_lot_not_marked_broker_missing(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "L-BBB": _lot("BBB", status="pending_fill"),
    }}
    oa = _FakeOA(positions=[])
    v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert "broker_missing" not in state["open_positions"]["L-BBB"]


def test_unrecoverable_state_with_broker_positions_always_halts(tmp_path):
    cfg = _cfg(tmp_path, reconcile={"halt_on_orphans": False})
    state = {"open_positions": {}}
    oa = _FakeOA(positions=[{"symbol": "AAA", "qty": 100}])
    rc = v2.reconcile_with_broker(
        state, cfg, oa_client=oa, api_key="k", http=None,
        state_parse_failed=True,
    )
    assert rc == 7


def test_fetch_failure_skips_reconciliation(tmp_path):
    cfg = _cfg(tmp_path)

    class _Boom:
        def fetch_positions(self, http, api_key):
            raise RuntimeError("network down")

    rc = v2.reconcile_with_broker(
        {"open_positions": {}}, cfg, oa_client=_Boom(), api_key="k",
        http=None,
    )
    assert rc is None


# ---- rollover exposure recompute ----------------------------------------


def test_rollover_recomputes_exposure_from_open_lots(tmp_path):
    cfg = _cfg(tmp_path)
    Path(cfg["paths"]["candidate_events_path"]).write_text("")
    state = {
        "session_date": "2026-05-18",
        "entered_today": ["AAA"], "daily_entries_count": 1,
        "daily_realized_pnl_strategy": -50.0,
        "gross_exposure_dollars": 99999.0,        # drifted value
        "last_consumed_event_offset": 0,
        "open_positions": {
            "L-AAA": _lot("AAA", recorded_exposure=4000.0),
            "L-BBB": _lot("BBB", recorded_exposure=None,
                          qty=200, entry_price=5.0),
        },
    }
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-19",
        now_utc=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )
    # 4000 (recorded) + 200*5.0 (fallback) = 5000, not 0, not 99999.
    assert state["gross_exposure_dollars"] == pytest.approx(5000.0)
    assert state["daily_entries_count"] == 0


def test_recompute_gross_exposure_empty_state():
    assert v2._recompute_gross_exposure({}) == 0.0
    assert v2._recompute_gross_exposure({"open_positions": {}}) == 0.0


# ---- exposure symmetry ---------------------------------------------------


def _candidate(symbol: str) -> dict:
    scan_ts = "2026-05-18T14:35:00Z"
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
        "candidate_rank": 1,
        "signal_expiry_timestamp": "2026-05-18T23:59:00Z",
    }


def test_entry_fill_close_round_trip_exposure_returns_to_zero(tmp_path):
    """Entry books signal-price notional; the fill trues it up to the
    actual fill notional; the close subtracts recorded_exposure —
    gross lands at exactly 0 even when fill price != signal price."""
    cfg = _cfg(tmp_path)
    cand_path = Path(cfg["paths"]["candidate_events_path"])
    cand_path.write_text(json.dumps(_candidate("AAA")) + "\n")
    state = {"last_consumed_event_offset": 0, "entered_today": [],
             "daily_entries_count": 0, "open_positions": {},
             "gross_exposure_dollars": 0.0}
    s = v2.consume_candidate_events(
        state, cfg,
        submit_supplier=lambda sym, qty: {
            "_http_status": 200, "data": {"order_id": "P-1"}},
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
    )
    assert s["accepted"] == 1
    pos_id, pos = next(iter(state["open_positions"].items()))
    qty = pos["qty"]
    assert state["gross_exposure_dollars"] == pytest.approx(qty * 8.11)

    # Parent fills at a DIFFERENT price (8.50) and a smaller qty.
    filled_qty = qty - 3
    oa = _FakeOA(orders=[{
        "id": "P-1", "status": "filled", "filled_qty": filled_qty,
        "filled_avg_price": 8.50,
    }])
    events = v2.poll_fills_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert len(events) == 1
    assert pos["recorded_exposure"] == pytest.approx(filled_qty * 8.50)
    assert state["gross_exposure_dollars"] == pytest.approx(
        filled_qty * 8.50)

    # Close at any price — exposure returns to exactly 0.
    rec = v2.close_position_v2(
        pos_id, state, cfg, exit_price=9.00, reason="target_hit",
    )
    assert rec is not None
    assert state["gross_exposure_dollars"] == pytest.approx(0.0)


# ---- daily state backups --------------------------------------------------


def test_backup_written_once_per_session_date(tmp_path):
    sp = tmp_path / "state.json"
    state = {"x": 1}
    now = datetime(2026, 7, 13, 10, 0)
    bak = v2.backup_state_daily(state, sp, now_et=now)
    assert bak is not None and bak.name == "state.json.bak_20260713"
    assert json.loads(bak.read_text())["x"] == 1
    # Second call same date: no-op.
    assert v2.backup_state_daily(state, sp, now_et=now) is None


def test_backup_prunes_to_keep_newest_5(tmp_path):
    sp = tmp_path / "state.json"
    for d in range(1, 8):                        # 7 old backups
        (tmp_path / f"state.json.bak_2026070{d}").write_text("{}")
    v2.backup_state_daily({"x": 1}, sp,
                          now_et=datetime(2026, 7, 13, 10, 0))
    baks = sorted(p.name for p in tmp_path.glob("state.json.bak_*"))
    assert len(baks) == 5
    assert baks[-1] == "state.json.bak_20260713"
    assert "state.json.bak_20260701" not in baks
