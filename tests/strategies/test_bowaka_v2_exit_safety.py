"""Hardening Phase 2 — exit-path safety.

Covers:
- trigger_exit_v2 aborts (no market sell) when a child cancel fails,
- run_time_stop_pass_v2 fires only inside the 15:15-15:55 ET
  business-day window (never at the midnight ET date flip),
- process_fill_events_v2 defers closures with no usable price
  instead of booking exit_price=0.0 (-100% phantom PnL),
- submit_oco_children_v2 treats ambiguous OCO legs as attach failure
  (no guessed ids stored).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

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


def _cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "session": {"start": "09:30", "end": "15:55"},
        "exits": {
            "stop_pct": 0.05, "target_pct": 0.10,
            "max_hold_days": 2, "oco_time_in_force": "GTC",
            "time_stop": {"enabled": True, "exit_time": "15:15"},
        },
        "protected_position": {
            "enabled": True, "max_unprotected_seconds": 5,
            "flatten_if_unprotected": True,
        },
        "logging": {"log_protection_state": True},
    }


def _ledger_events(tmp_path) -> list[dict]:
    p = Path(tmp_path / "trade_ledger.jsonl")
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines()]


class FakeOA:
    def __init__(self):
        self.cancel_calls: list[str] = []
        self.market_sells: list[dict] = []
        self.cancel_responses: dict[str, dict] = {}
        self.cancel_raises: set[str] = set()
        self.oco_response = {"_http_status": 200, "data": {}}

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        if order_id in self.cancel_raises:
            raise RuntimeError("network down")
        return self.cancel_responses.get(
            order_id, {"status": "canceled", "order_id": order_id},
        )

    def submit_market_sell(self, http, api_key, *, venue_code, symbol,
                           qty, time_in_force="DAY"):
        self.market_sells.append({"symbol": symbol, "qty": qty})
        return {"data": {"order_id": "EXIT-1"}, "_http_status": 200}

    def submit_oco_bracket(self, http, api_key, **kwargs):
        return self.oco_response


def _filled_pos(**over) -> dict:
    pos = {
        "symbol": "AAA", "qty": 100, "venue_code": "XNAS",
        "status": "filled", "entry_price": 10.00,
        "entry_timestamp": "2026-05-18T13:31:00Z",
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "link_id": "L-1",
        "target_pct": 0.10, "stop_pct": 0.05,
        "target_price": 11.00, "stop_price": 9.50,
    }
    pos.update(over)
    return pos


# ---- 2a: cancel verification ------------------------------------------


def test_exit_aborts_when_child_cancel_errors(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos()
    oa = FakeOA()
    oa.cancel_responses["S-1"] = {
        "status": "error", "order_id": "S-1", "http_status": 500,
    }
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="time_stop",
    )
    assert ok is False
    assert oa.market_sells == []                 # no market sell
    assert pos["status"] == "filled"             # reverted for retry
    assert "exit_reason_pending" not in pos
    events = _ledger_events(tmp_path)
    aborted = [e for e in events
               if e["event_type"] == "exit_aborted_cancel_failed"]
    assert aborted and aborted[0]["order_id"] == "S-1"


def test_exit_aborts_when_cancel_raises(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos()
    oa = FakeOA()
    oa.cancel_raises.add("T-1")
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is False
    assert oa.market_sells == []
    assert pos["status"] == "filled"


def test_exit_proceeds_when_all_cancels_confirmed(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos()
    oa = FakeOA()
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="time_stop",
    )
    assert ok is True
    assert sorted(oa.cancel_calls) == ["S-1", "T-1"]
    assert len(oa.market_sells) == 1
    assert pos["status"] == "exiting"


# ---- 2b: time-stop window ----------------------------------------------


def _held_state() -> dict:
    return {"open_positions": {
        "L-1": _filled_pos(entry_timestamp="2026-05-08T13:30:00Z"),
    }}


def test_time_stop_does_not_fire_at_midnight(tmp_path):
    cfg = _cfg(tmp_path)
    state = _held_state()
    oa = FakeOA()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 0, 5),      # 00:05 ET Monday
    )
    assert out == []
    assert oa.cancel_calls == []                 # OCO left alone
    assert state["open_positions"]["L-1"]["status"] == "filled"


def test_time_stop_fires_in_window_on_business_day(tmp_path):
    cfg = _cfg(tmp_path)
    state = _held_state()
    oa = FakeOA()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 15, 20),    # Monday 15:20 ET
    )
    assert out == ["AAA"]
    assert state["open_positions"]["L-1"]["status"] == "exiting"


def test_time_stop_skips_weekend(tmp_path):
    cfg = _cfg(tmp_path)
    state = _held_state()
    oa = FakeOA()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 16, 15, 20),    # Saturday
    )
    assert out == []


def test_time_stop_skips_after_session_end(tmp_path):
    cfg = _cfg(tmp_path)
    state = _held_state()
    oa = FakeOA()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 16, 30),    # after 15:55
    )
    assert out == []


def test_time_stop_disabled_skips_pass(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["exits"]["time_stop"]["enabled"] = False
    state = _held_state()
    oa = FakeOA()
    out = v2.run_time_stop_pass_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
        now_et=datetime(2026, 5, 18, 15, 20),
    )
    assert out == []


# ---- 2c: no 0.0 closures ------------------------------------------------


def test_fill_with_no_price_defers_closure(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos(target_price=None, stop_price=None)
    state = {"open_positions": {"L-1": pos},
             "daily_realized_pnl_strategy": 0.0}
    events = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "S-1",
        "role": "stop", "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": None, "raw": {},
    }]
    closures = v2.process_fill_events_v2(events, state, cfg)
    assert closures == []
    assert "L-1" in state["open_positions"]      # lot survives
    assert pos["exit_price_pending"] is True
    assert state["daily_realized_pnl_strategy"] == 0.0
    ledger = _ledger_events(tmp_path)
    deferred = [e for e in ledger
                if e["event_type"] == "closure_deferred_no_price"]
    assert len(deferred) == 1
    # Second echo without a price: still deferred, ledger NOT repeated.
    v2.process_fill_events_v2(events, state, cfg)
    ledger = _ledger_events(tmp_path)
    deferred = [e for e in ledger
                if e["event_type"] == "closure_deferred_no_price"]
    assert len(deferred) == 1


def test_later_priced_echo_closes_normally(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos(target_price=None, stop_price=None)
    state = {"open_positions": {"L-1": pos},
             "daily_realized_pnl_strategy": 0.0,
             "gross_exposure_dollars": 1000.0}
    no_price = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "S-1",
        "role": "stop", "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": None, "raw": {},
    }]
    v2.process_fill_events_v2(no_price, state, cfg)
    assert "L-1" in state["open_positions"]
    priced = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "S-1",
        "role": "stop", "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": 9.50, "raw": {},
    }]
    closures = v2.process_fill_events_v2(priced, state, cfg)
    assert len(closures) == 1
    assert closures[0]["exit_price"] == pytest.approx(9.50)
    assert closures[0]["realized_pnl"] == pytest.approx(-50.0)
    assert "L-1" not in state["open_positions"]


def test_stop_fill_falls_back_to_stored_stop_price(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_pos()                          # stop_price 9.50
    state = {"open_positions": {"L-1": pos}}
    events = [{
        "symbol": "AAA", "pos_id": "L-1", "order_id": "S-1",
        "role": "stop", "status": "FILLED", "filled_qty": 100,
        "filled_avg_price": None, "raw": {},
    }]
    closures = v2.process_fill_events_v2(events, state, cfg)
    assert len(closures) == 1
    assert closures[0]["exit_price"] == pytest.approx(9.50)


# ---- 2d: strict OCO leg parsing -----------------------------------------


def _oco_pos() -> dict:
    return _filled_pos(child_order_ids={"target": "", "stop": ""})


def _oco_response(legs) -> dict:
    return {
        "_http_status": 200,
        "data": {"native_response": {"id": "PARENT-OCO", "legs": legs}},
    }


@pytest.mark.parametrize("legs", [
    # both legs limit — cannot tell stop from target
    [{"id": "A", "order_type": "limit"},
     {"id": "B", "order_type": "limit"}],
    # ids missing entirely
    [{"order_type": "limit"}, {"order_type": "stop"}],
    # duplicate ids
    [{"id": "X", "order_type": "limit"},
     {"id": "X", "order_type": "stop"}],
    # no legs at all
    [],
])
def test_ambiguous_oco_legs_fail_attach(tmp_path, legs):
    cfg = _cfg(tmp_path)
    pos = _oco_pos()
    oa = FakeOA()
    oa.oco_response = _oco_response(legs)
    res = v2.submit_oco_children_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert isinstance(res, dict) and "error" in res
    assert pos["child_order_ids"] == {"target": "", "stop": ""}
    assert "oco_attached_at" not in pos
    ledger = _ledger_events(tmp_path)
    assert any(e["event_type"] == "bracket_attach_ambiguous"
               for e in ledger)


def test_clean_oco_legs_attach_normally(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _oco_pos()
    oa = FakeOA()
    oa.oco_response = _oco_response([
        {"id": "TGT-1", "order_type": "limit"},
        {"id": "STP-1", "order_type": "stop"},
    ])
    res = v2.submit_oco_children_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert res is not None and "error" not in res
    assert pos["child_order_ids"] == {"target": "TGT-1", "stop": "STP-1"}
    assert "oco_attached_at" in pos


def test_stop_limit_leg_classifies_as_stop(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _oco_pos()
    oa = FakeOA()
    oa.oco_response = _oco_response([
        {"id": "TGT-1", "order_type": "limit"},
        {"id": "STP-1", "order_type": "stop_limit"},
    ])
    res = v2.submit_oco_children_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert res is not None and "error" not in res
    assert pos["child_order_ids"]["stop"] == "STP-1"
