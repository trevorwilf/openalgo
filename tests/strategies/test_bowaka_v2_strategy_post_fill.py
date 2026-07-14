"""Phase 6 — v2 strategy post-fill plumbing.

OCO bracket attach, fill polling, exit-on-time-stop / kill-switch /
unprotected-position invariants, and the corresponding ledger /
closure-summary emissions. All tests inject a fake oa_client surrogate
so no broker network I/O happens.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import bowaka_v2_strategy as v2


# ---------- shared fixtures ----------


@pytest.fixture(autouse=True)
def _redirect_v2_paths(tmp_path, monkeypatch):
    """Redirect v2 logging paths to tmp_path for each test."""
    import bowaka_v2_paths as p
    monkeypatch.setattr(p, "PROTECTION_EVENTS_PATH",
                         tmp_path / "protection_events.jsonl")
    monkeypatch.setattr(p, "V2_LEDGER_PATH",
                         tmp_path / "trade_ledger.jsonl")
    monkeypatch.setattr(p, "V2_DAILY_SUMMARY_PATH",
                         tmp_path / "daily_summary.jsonl")


def _cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
            "state_path": str(tmp_path / "state.json"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "exits": {
            "stop_pct": 0.05, "target_pct": 0.10,
            "max_hold_days": 2, "oco_time_in_force": "GTC",
        },
        "protected_position": {
            "enabled": True, "max_unprotected_seconds": 5,
            "flatten_if_unprotected": True,
        },
        "logging": {
            "log_protection_state": True,
        },
    }


class FakeOAClient:
    """Drop-in surrogate for bowaka_v2_openalgo_client. Each method
    records its call and returns a canned response."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.market_sell_response = {
            "data": {"order_id": "EXIT-1"}, "_http_status": 200,
        }
        self.oco_response = {
            "_http_status": 200,
            "data": {
                "native_response": {
                    "id": "PARENT-OCO-1",
                    "legs": [
                        {"id": "TARGET-1", "order_type": "limit"},
                        {"id": "STOP-1", "order_type": "stop"},
                    ],
                },
            },
        }
        self.fetched_orders: list[dict] = []
        self.cancel_calls: list[str] = []

    def submit_market_sell(self, http, api_key, *, venue_code, symbol,
                            qty, time_in_force="DAY"):
        self.calls.append(("submit_market_sell", {
            "venue_code": venue_code, "symbol": symbol,
            "qty": qty, "time_in_force": time_in_force,
        }))
        return self.market_sell_response

    def submit_oco_bracket(self, http, api_key, *, venue_code, symbol,
                            qty, target_price, stop_price, link_id,
                            time_in_force="GTC"):
        self.calls.append(("submit_oco_bracket", {
            "venue_code": venue_code, "symbol": symbol, "qty": qty,
            "target_price": target_price, "stop_price": stop_price,
            "link_id": link_id, "time_in_force": time_in_force,
        }))
        return self.oco_response

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        return {"status": "canceled", "order_id": order_id}

    def fetch_all_orders(self, http, api_key):
        return list(self.fetched_orders)


# ---------- record_pending_position ----------


def test_record_pending_position_writes_state(tmp_path):
    state = {"open_positions": {}}
    v2.record_pending_position(
        state, symbol="AAA", qty=100, venue_code="XNAS",
        parent_order_id="P-1", link_id="L-1",
        candidate_close=10.0, signal_strength=5.0,
        equity_at_entry=90000, entry_features={"rvol": 3.0},
        stop_pct=0.05, target_pct=0.10, max_hold_days=2,
        candidate_event_id="evt-1",
    )
    pos = state["open_positions"]["L-1"]
    assert pos["status"] == "pending_fill"
    assert pos["parent_order_id"] == "P-1"
    assert pos["qty"] == 100
    assert pos["entry_price"] is None
    assert pos["child_order_ids"] == {"target": "", "stop": ""}
    assert pos["stop_pct"] == 0.05
    assert pos["target_pct"] == 0.10
    assert pos["candidate_event_id"] == "evt-1"


# ---------- poll_fills_v2 parent fill ----------


def test_poll_fills_v2_parent_fill_marks_position_filled(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {}}
    v2.record_pending_position(
        state, symbol="AAA", qty=100, venue_code="XNAS",
        parent_order_id="P-1", link_id="L-1",
        candidate_close=10.0, signal_strength=5.0,
        equity_at_entry=90000, entry_features={},
        stop_pct=0.05, target_pct=0.10, max_hold_days=2,
        candidate_event_id="evt-1",
    )
    oa = FakeOAClient()
    oa.fetched_orders = [{
        "id": "P-1", "native_status": "filled",
        "filled_qty": 100, "filled_avg_price": "10.50",
    }]
    events = v2.poll_fills_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert len(events) == 1
    assert events[0]["role"] == "parent"
    pos = state["open_positions"]["L-1"]
    assert pos["status"] == "filled"
    assert pos["entry_price"] == 10.50
    assert pos["parent_fill_processed"] is True
    assert pos["peak_since_entry"] == 10.50
    assert pos["trough_since_entry"] == 10.50


def test_poll_fills_v2_duplicate_parent_fill_is_idempotent(tmp_path):
    """A second poll that surfaces the same FILLED parent row is a
    no-op (no peak/trough reset, no duplicate ledger entry)."""
    cfg = _cfg(tmp_path)
    state = {"open_positions": {}}
    v2.record_pending_position(
        state, symbol="AAA", qty=100, venue_code="XNAS",
        parent_order_id="P-1", link_id="L-1",
        candidate_close=10.0, signal_strength=5.0,
        equity_at_entry=90000, entry_features={},
        stop_pct=0.05, target_pct=0.10, max_hold_days=2,
        candidate_event_id="evt-1",
    )
    oa = FakeOAClient()
    oa.fetched_orders = [{
        "id": "P-1", "native_status": "filled",
        "filled_qty": 100, "filled_avg_price": "10.50",
    }]
    v2.poll_fills_v2(state, cfg, oa_client=oa, api_key="k", http=None)
    pos = state["open_positions"]["L-1"]
    pos["peak_since_entry"] = 11.20  # drift the peak
    pos["status"] = "filled"
    events2 = v2.poll_fills_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert len(events2) == 0  # idempotent
    assert pos["peak_since_entry"] == 11.20  # not reset


def test_poll_fills_v2_parent_rejected_drops_position(tmp_path):
    """A REJECTED/CANCELED parent with no partial fill should evict
    the position entirely."""
    cfg = _cfg(tmp_path)
    state = {"open_positions": {}}
    v2.record_pending_position(
        state, symbol="AAA", qty=100, venue_code="XNAS",
        parent_order_id="P-1", link_id="L-1",
        candidate_close=10.0, signal_strength=5.0,
        equity_at_entry=90000, entry_features={},
        stop_pct=0.05, target_pct=0.10, max_hold_days=2,
        candidate_event_id="evt-1",
    )
    oa = FakeOAClient()
    oa.fetched_orders = [{
        "id": "P-1", "native_status": "rejected",
        "filled_qty": 0, "filled_avg_price": None,
    }]
    v2.poll_fills_v2(state, cfg, oa_client=oa, api_key="k", http=None)
    assert "L-1" not in state["open_positions"]


# ---------- submit_oco_children_v2 ----------


def test_submit_oco_children_v2_attaches_bracket(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {}}
    v2.record_pending_position(
        state, symbol="AAA", qty=100, venue_code="XNAS",
        parent_order_id="P-1", link_id="L-1",
        candidate_close=10.0, signal_strength=5.0,
        equity_at_entry=90000, entry_features={},
        stop_pct=0.05, target_pct=0.10, max_hold_days=2,
        candidate_event_id="evt-1",
    )
    pos = state["open_positions"]["L-1"]
    pos["status"] = "filled"
    pos["entry_price"] = 10.00
    oa = FakeOAClient()
    res = v2.submit_oco_children_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert res is not None and "error" not in res
    # target = 10 * 1.10 = 11.00 ; stop = 10 * 0.95 = 9.50
    assert pos["target_price"] == 11.00
    assert pos["stop_price"] == 9.50
    assert pos["child_order_ids"]["target"] == "TARGET-1"
    assert pos["child_order_ids"]["stop"] == "STOP-1"
    # OCO call carried target/stop/qty.
    name, kw = oa.calls[0]
    assert name == "submit_oco_bracket"
    assert kw["symbol"] == "AAA"
    assert kw["qty"] == 100
    assert kw["target_price"] == 11.00
    assert kw["stop_price"] == 9.50


def test_submit_oco_children_v2_idempotent(tmp_path):
    """Already-bracketed position short-circuits to None."""
    cfg = _cfg(tmp_path)
    pos = {
        "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
        "entry_price": 10.00, "status": "filled",
        "stop_pct": 0.05, "target_pct": 0.10,
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "link_id": "L-1",
    }
    oa = FakeOAClient()
    res = v2.submit_oco_children_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert res is None
    assert oa.calls == []


def test_submit_pending_oco_children_v2_sweep(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "AAA": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "entry_price": 10.00, "status": "filled",
            "stop_pct": 0.05, "target_pct": 0.10,
            "child_order_ids": {"target": "", "stop": ""},
            "link_id": "L-1",
        },
        "BBB": {  # already protected — sweep skips it.
            "symbol": "BBB", "qty": 50, "venue_code": "XNAS",
            "entry_price": 5.00, "status": "filled",
            "stop_pct": 0.05, "target_pct": 0.10,
            "child_order_ids": {"target": "T-B", "stop": "S-B"},
        },
        "CCC": {  # not yet filled.
            "symbol": "CCC", "qty": 30, "venue_code": "XNAS",
            "entry_price": None, "status": "pending_fill",
            "child_order_ids": {"target": "", "stop": ""},
        },
    }}
    oa = FakeOAClient()
    out = v2.submit_pending_oco_children_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == ["AAA"]


# ---------- close_position_v2 ----------


def test_close_position_v2_writes_closure_and_drops_pos(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "open_positions": {
            "AAA": {
                "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
                "entry_price": 10.00, "status": "filled",
                "entry_timestamp": "2026-05-15T13:30:00Z",
                "link_id": "L-1",
                "target_pct": 0.10, "stop_pct": 0.05,
                "target_price": 11.00, "stop_price": 9.50,
                "peak_since_entry": 11.20,
                "trough_since_entry": 9.80,
            },
        },
        "gross_exposure_dollars": 1000.0,
    }
    rec = v2.close_position_v2(
        "AAA", state, cfg, exit_price=11.00, reason="target_hit",
    )
    assert rec is not None
    assert rec["realized_pnl"] == pytest.approx(100.0)
    assert rec["reason"] == "target_hit"
    assert rec["peak_since_entry"] == 11.20
    assert rec["trough_since_entry"] == 9.80
    assert "AAA" not in state["open_positions"]
    assert state["gross_exposure_dollars"] == 0.0
    summary_path = Path(cfg["paths"]["daily_summary_path"])
    assert summary_path.exists()
    line = summary_path.read_text().splitlines()[0]
    assert json.loads(line)["reason"] == "target_hit"


def test_process_fill_events_v2_target_closes_position(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "L-1": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "entry_price": 10.00, "status": "filled",
            "entry_timestamp": "2026-05-15T13:30:00Z",
            "link_id": "L-1",
            "target_pct": 0.10, "stop_pct": 0.05,
            "target_price": 11.00, "stop_price": 9.50,
            "peak_since_entry": 11.00, "trough_since_entry": 9.80,
        },
    }}
    events = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "T-1", "role": "target",
        "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": 11.00, "raw": {},
    }]
    closures = v2.process_fill_events_v2(events, state, cfg)
    assert len(closures) == 1
    assert closures[0]["reason"] == "target_hit"
    assert "L-1" not in state["open_positions"]


def test_process_fill_events_v2_stop_closes_position(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "L-1": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "entry_price": 10.00, "status": "filled",
            "entry_timestamp": "2026-05-15T13:30:00Z",
            "link_id": "L-1",
            "target_pct": 0.10, "stop_pct": 0.05,
            "target_price": 11.00, "stop_price": 9.50,
            "peak_since_entry": 10.50, "trough_since_entry": 9.50,
        },
    }}
    events = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "S-1", "role": "stop",
        "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": 9.50, "raw": {},
    }]
    closures = v2.process_fill_events_v2(events, state, cfg)
    assert len(closures) == 1
    assert closures[0]["reason"] == "stop_hit"
    assert closures[0]["realized_pnl"] == pytest.approx(-50.0)


# ---------- trigger_exit_v2 ----------


def test_trigger_exit_v2_cancels_children_then_market_sells(tmp_path):
    cfg = _cfg(tmp_path)
    pos = {
        "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
        "status": "filled", "entry_price": 10.00,
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "link_id": "L-1",
    }
    oa = FakeOAClient()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="time_stop", time_in_force="DAY",
    )
    assert ok is True
    assert sorted(oa.cancel_calls) == ["S-1", "T-1"]
    assert any(name == "submit_market_sell" for name, _ in oa.calls)
    assert pos["status"] == "exiting"
    assert pos["exit_order_id"] == "EXIT-1"
    assert pos["exit_reason"] == "time_stop"


def test_trigger_exit_v2_skips_when_not_filled(tmp_path):
    cfg = _cfg(tmp_path)
    pos = {
        "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
        "status": "exiting", "entry_price": 10.00,
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
    }
    oa = FakeOAClient()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is False
    assert oa.calls == []


def test_trigger_exit_v2_reverts_on_broker_rejection(tmp_path):
    cfg = _cfg(tmp_path)
    pos = {
        "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
        "status": "filled", "entry_price": 10.00,
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "link_id": "L-1",
    }
    oa = FakeOAClient()
    oa.market_sell_response = {
        "_http_status": 422, "error": {"code": "halt"},
    }
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is False
    assert pos["status"] == "filled"
    assert "exit_reason_pending" not in pos


# ---------- run_time_stop_pass_v2 ----------


def test_run_time_stop_pass_v2_exits_after_max_hold(tmp_path):
    cfg = _cfg(tmp_path)  # max_hold_days = 2
    # Entry 6 trading days before the injected now — must trip the
    # time stop. now_et = Monday 2026-05-18 15:20 ET, inside the
    # 15:15-15:55 in-session window.
    state = {"open_positions": {
        "AAA": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "status": "filled", "entry_price": 10.00,
            "entry_timestamp": "2026-05-08T13:30:00Z",
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "link_id": "L-1",
        },
    }}
    oa = FakeOAClient()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 15, 20),
    )
    assert out == ["AAA"]
    assert state["open_positions"]["AAA"]["status"] == "exiting"
    assert state["open_positions"]["AAA"]["exit_reason"] == "time_stop"


def test_run_time_stop_pass_v2_skips_recent_entries(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "AAA": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "status": "filled", "entry_price": 10.00,
            "entry_timestamp": "2026-05-18T13:30:00Z",  # same day
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "link_id": "L-1",
        },
    }}
    oa = FakeOAClient()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 15, 20),
    )
    assert out == []


# ---------- execute_kill_l2_v2 ----------


def test_execute_kill_l2_v2_flattens_filled_and_cancels_pending(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {
        "AAA": {  # filled — will be market-sold.
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "status": "filled", "entry_price": 10.00,
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "link_id": "L-A",
        },
        "BBB": {  # pending — cancel parent + children, drop.
            "symbol": "BBB", "qty": 50, "venue_code": "XNAS",
            "status": "pending_fill",
            "parent_order_id": "P-B",
            "child_order_ids": {"target": "", "stop": ""},
            "link_id": "L-B",
        },
    }}
    oa = FakeOAClient()
    out = v2.execute_kill_l2_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert sorted(out) == ["AAA", "BBB"]
    assert state["kill_switch_state"] == "L2"
    # BBB cancel attempted, position dropped.
    assert "P-B" in oa.cancel_calls
    assert "BBB" not in state["open_positions"]
    # AAA → exiting.
    assert state["open_positions"]["AAA"]["status"] == "exiting"


# ---------- enforce_protected_position_invariant_v2 ----------


def test_protected_position_invariant_flattens_unprotected(tmp_path):
    cfg = _cfg(tmp_path)  # max_unprotected_seconds = 5
    stale = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    state = {"open_positions": {
        "AAA": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "status": "filled", "entry_price": 10.00,
            "entry_timestamp": stale,
            "parent_fill_processed_at": stale,
            "child_order_ids": {"target": "", "stop": ""},
            "link_id": "L-1",
            "oco_attach_attempts": 2,
        },
    }}
    oa = FakeOAClient()
    out = v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == ["AAA"]
    assert state["open_positions"]["AAA"]["status"] == "exiting"


def test_protected_position_invariant_lets_protected_alone(tmp_path):
    cfg = _cfg(tmp_path)
    stale = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    state = {"open_positions": {
        "AAA": {
            "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
            "status": "filled", "entry_price": 10.00,
            "entry_timestamp": stale,
            "parent_fill_processed_at": stale,
            "child_order_ids": {"target": "T-1", "stop": "S-1"},
            "link_id": "L-1",
        },
    }}
    oa = FakeOAClient()
    out = v2.enforce_protected_position_invariant_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert out == []
    assert state["open_positions"]["AAA"]["status"] == "filled"


# ---------- consume_candidate_events captures parent_order_id ----------


def _make_candidate(symbol: str) -> dict:
    import bowaka_v2_schemas as schemas
    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": f"bowaka_v2:2026-05-18:{symbol}:scan",
        "generated_at": "2026-05-18T14:35:00Z",
        "session_date": "2026-05-18",
        "scan_timestamp": "2026-05-18T14:35:00Z",
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
        "signal_expiry_timestamp": "2026-05-19T00:00:00Z",
    }


def test_consumer_records_parent_order_id_from_submit(tmp_path, monkeypatch):
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {
            "candidate_events_path": str(cand_path),
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
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
        "risk": {"max_total_entries_per_day": 10,
                   "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {"emit_entry_decisions": False,
                       "emit_rejected_candidates": False,
                       "log_order_execution_quality": False,
                       "log_protection_state": False,
                       "log_shadow_risk_controls": False,
                       "log_counterfactual_entries": False,
                       "log_counterfactual_exits": False},
    }
    state = {
        "last_consumed_event_offset": 0, "entered_today": [],
        "daily_entries_count": 0, "open_positions": {},
    }

    def fake_submit(symbol, qty):
        return {
            "_http_status": 200,
            "data": {"order_id": f"PARENT-{symbol}"},
        }

    s = v2.consume_candidate_events(
        state, cfg,
        quote_supplier=lambda sym: {
            "bid": 8.10, "ask": 8.12, "mid": 8.11, "spread_pct": 0.002,
            "quote_timestamp": "2026-05-18T18:35:00Z",
            "quote_age_seconds": 1, "symbol_status": "ok",
        },
        submit_supplier=fake_submit,
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
    )
    assert s["accepted"] == 1
    pos = v2.lots_for_symbol(state, "AAA")[0]
    assert pos["parent_order_id"] == "PARENT-AAA"
    assert pos["status"] == "pending_fill"
    assert pos["qty"] > 0
    assert pos["candidate_event_id"] is not None


def test_consumer_rolls_over_per_day_counters_on_new_session(tmp_path):
    """A state carried over from a prior ET date must have its
    per-day counters cleared on first consume of the new date."""
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text("")
    cfg = {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {"candidate_events_path": str(cand_path),
                    "trade_ledger_path": str(tmp_path / "l.jsonl"),
                    "daily_summary_path": str(tmp_path / "ds.jsonl")},
        "data": {"feed": "iex", "allow_non_sip_for_research_only": True},
        "execution": {
            "default_venue_code": "XNAS",
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
        "risk": {"max_total_entries_per_day": 10,
                   "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {k: False for k in (
            "emit_entry_decisions", "emit_rejected_candidates",
            "log_order_execution_quality", "log_protection_state",
            "log_shadow_risk_controls", "log_counterfactual_entries",
            "log_counterfactual_exits",
        )},
    }
    state = {
        "session_date": "2026-05-18",
        "entered_today": ["AAA", "BBB"],
        "daily_entries_count": 5,
        "daily_realized_pnl_strategy": -123.45,
        "gross_exposure_dollars": 30000.0,
        "last_consumed_event_offset": 0,
        "open_positions": {},
    }
    v2.consume_candidate_events(
        state, cfg, today_iso="2026-05-19",
        now_utc=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
    )
    assert state["session_date"] == "2026-05-19"
    assert state["entered_today"] == []
    assert state["daily_entries_count"] == 0
    assert state["daily_realized_pnl_strategy"] == 0.0
    assert state["gross_exposure_dollars"] == 0.0


def test_consumer_skips_state_record_on_submit_rejection(tmp_path):
    cand_path = tmp_path / "candidates.jsonl"
    cand_path.write_text(json.dumps(_make_candidate("AAA")) + "\n")
    cfg = {
        "strategy": {"mode": "forming_daily_bar_monitor",
                       "environment": "paper"},
        "paths": {"candidate_events_path": str(cand_path),
                    "trade_ledger_path": str(tmp_path / "ledger.jsonl"),
                    "daily_summary_path": str(tmp_path / "ds.jsonl")},
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
        "risk": {"max_total_entries_per_day": 10,
                   "max_gross_exposure_pct": 0.80},
        "exits": {"stop_pct": 0.08, "target_pct": 0.15,
                    "max_hold_days": 3},
        "logging": {k: False for k in (
            "emit_entry_decisions", "emit_rejected_candidates",
            "log_order_execution_quality", "log_protection_state",
            "log_shadow_risk_controls", "log_counterfactual_entries",
            "log_counterfactual_exits",
        )},
    }
    state = {
        "last_consumed_event_offset": 0, "entered_today": [],
        "daily_entries_count": 0, "open_positions": {},
    }

    def fake_reject(symbol, qty):
        return {"_http_status": 422, "error": {"code": "halt"}}

    s = v2.consume_candidate_events(
        state, cfg,
        submit_supplier=fake_reject,
        today_iso="2026-05-18",
        now_utc=datetime(2026, 5, 18, 18, 35, tzinfo=timezone.utc),
    )
    assert s["accepted"] == 0
    assert s["rejected"] >= 1
    assert "AAA" not in state["open_positions"]
