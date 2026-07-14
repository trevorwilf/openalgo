"""Fix Phase 2 — cancel/fill races.

OpenAlgo wraps Alpaca's ASYNC cancel: a cancel-accept only means
``pending_cancel`` and the order can still fill. These tests script
the race matrix against a fake oa_client:

- trigger_exit_v2 verifies each accepted child cancel went terminal
  before the market sell; a child that FILLED during the cancel
  aborts the exit (no sell → no accidental short).
- the pending-fill janitor adopts a lot whose parent cancel raced a
  fill, and never drops a lot whose parent state is unknown.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

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


@pytest.fixture(autouse=True)
def _fast_cancel_verify(monkeypatch):
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_ATTEMPTS", 3)
    monkeypatch.setattr(v2, "_CANCEL_VERIFY_SLEEP_S", 0.0)


def _cfg(tmp_path):
    return {
        "paths": {
            "trade_ledger_path": str(tmp_path / "trade_ledger.jsonl"),
            "daily_summary_path": str(tmp_path / "daily_summary.jsonl"),
        },
        "execution": {"default_venue_code": "XNAS"},
        "exits": {"stop_pct": 0.05, "target_pct": 0.10,
                  "max_hold_days": 2, "oco_time_in_force": "GTC"},
        "logging": {"log_protection_state": True},
    }


def _ledger_events(tmp_path) -> list[dict]:
    p = tmp_path / "trade_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


class ScriptedOA:
    """oa_client surrogate with scripted cancel results and per-order
    status-row queues (last row repeats)."""

    def __init__(self):
        self.cancel_results: dict[str, object] = {}
        self.order_rows: dict[str, list] = {}
        self.cancel_calls: list[str] = []
        self.fetch_order_calls: list[str] = []
        self.market_sells: list[dict] = []
        self.market_sell_response = {
            "data": {"order_id": "EXIT-1"}, "_http_status": 200,
        }

    def cancel_order(self, http, api_key, order_id):
        self.cancel_calls.append(order_id)
        res = self.cancel_results.get(
            order_id, {"status": "canceled", "order_id": order_id},
        )
        if isinstance(res, Exception):
            raise res
        return res

    def fetch_order(self, http, api_key, order_id):
        self.fetch_order_calls.append(order_id)
        queue = self.order_rows.get(order_id)
        if not queue:
            return None
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    def fetch_all_orders(self, http, api_key):
        return []

    def submit_market_sell(self, http, api_key, *, venue_code, symbol,
                            qty, time_in_force="DAY"):
        self.market_sells.append({"symbol": symbol, "qty": qty})
        return self.market_sell_response

    def submit_limit_sell(self, http, api_key, *, venue_code, symbol,
                           qty, price, time_in_force="DAY"):
        self.market_sells.append({"symbol": symbol, "qty": qty,
                                  "price": price})
        return self.market_sell_response


def _row(oid, status, filled_qty=0, fap=None):
    return {"id": oid, "status": status, "filled_qty": filled_qty,
            "filled_avg_price": fap}


def _filled_lot(symbol="AAA", target="T-1", stop="S-1"):
    return {
        "symbol": symbol, "qty": 100, "status": "filled",
        "link_id": f"L-{symbol}", "entry_price": 10.0,
        "entry_timestamp": "2026-07-10T14:00:00Z",
        "recorded_exposure": 1000.0,
        "child_order_ids": {"target": target, "stop": stop},
        "target_price": 11.0, "stop_price": 9.5,
        "parent_order_id": "P-1",
    }


# ---- trigger_exit_v2 ---------------------------------------------------------


def test_trigger_exit_aborts_when_child_filled_during_cancel(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot(stop="")  # single target child
    oa = ScriptedOA()
    oa.order_rows["T-1"] = [_row("T-1", "filled", 100, 11.05)]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
        reason="time_stop",
    )
    assert ok is False
    assert oa.market_sells == []          # never sell after a raced fill
    assert pos["status"] == "filled"       # fill echo books the closure
    assert "exit_reason_pending" not in pos
    events = _ledger_events(tmp_path)
    assert any(e["event_type"] == "exit_aborted_child_filled"
               for e in events)


def test_trigger_exit_partial_fill_on_canceled_child_counts_as_filled(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot(stop="")
    oa = ScriptedOA()
    # Terminal canceled but 40 shares traded first — partial counts.
    oa.order_rows["T-1"] = [_row("T-1", "canceled", 40, 11.0)]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is False
    assert oa.market_sells == []
    assert any(e["event_type"] == "exit_aborted_child_filled"
               for e in _ledger_events(tmp_path))


def test_trigger_exit_proceeds_when_cancels_confirm_terminal(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot()
    oa = ScriptedOA()
    oa.order_rows["T-1"] = [_row("T-1", "canceled")]
    oa.order_rows["S-1"] = [_row("S-1", "canceled")]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is True
    assert pos["status"] == "exiting"
    assert len(oa.market_sells) == 1
    assert sorted(oa.cancel_calls) == ["S-1", "T-1"]


def test_trigger_exit_verify_timeout_aborts_then_retries(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot(stop="")
    oa = ScriptedOA()
    # Never goes terminal within the verify budget.
    oa.order_rows["T-1"] = [_row("T-1", "pending_cancel")]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is False
    assert pos["status"] == "filled"       # retryable
    assert oa.market_sells == []
    assert any(e["event_type"] == "exit_aborted_cancel_unconfirmed"
               for e in _ledger_events(tmp_path))
    # Next tick: the cancel has landed — the retry completes the exit.
    oa.order_rows["T-1"] = [_row("T-1", "canceled")]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is True
    assert len(oa.market_sells) == 1


def test_trigger_exit_not_found_after_cancel_accept_is_canceled(tmp_path):
    cfg = _cfg(tmp_path)
    pos = _filled_lot(stop="")
    oa = ScriptedOA()
    oa.order_rows["T-1"] = [{"_status": "not_found"},
                             {"_status": "not_found"},
                             {"_status": "not_found"}]
    ok = v2.trigger_exit_v2(
        "AAA", pos, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert ok is True
    assert len(oa.market_sells) == 1


# ---- janitor -----------------------------------------------------------------


def _pending_lot(symbol="AAA", parent="P-1", exposure=4000.0):
    return {
        "symbol": symbol, "qty": 400, "venue_code": "XNAS",
        "parent_order_id": parent, "link_id": f"L-{symbol}",
        "child_order_ids": {"target": "", "stop": ""},
        "status": "pending_fill", "entry_price": None,
        "entry_timestamp": "2026-05-18T18:30:00Z",
        "recorded_exposure": exposure,
        "stop_pct": 0.08, "target_pct": 0.15, "max_hold_days": 3,
    }


_NOW = datetime(2026, 5, 18, 19, 0, tzinfo=timezone.utc)  # lot is 30m old


def test_janitor_adopts_lot_when_cancel_raced_fill(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.order_rows["P-1"] = [_row("P-1", "filled", 400, 10.5)]
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == []                       # NOT dropped
    pos = state["open_positions"]["L-AAA"]
    assert pos["status"] == "filled"
    assert pos["entry_price"] == 10.5
    assert pos["qty"] == 400
    assert pos["parent_fill_processed"] is True
    # Exposure trued up to the actual fill notional (400 x 10.5).
    assert pos["recorded_exposure"] == 4200.0
    assert state["gross_exposure_dollars"] == 4200.0
    events = _ledger_events(tmp_path)
    assert any(e["event_type"] == "janitor_cancel_raced_fill"
               for e in events)
    assert not any(e["event_type"] == "pending_fill_expired"
                   for e in events)


def test_janitor_retains_lot_when_cancel_errors_and_parent_live(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.cancel_results["P-1"] = {"status": "error", "http_status": 500}
    oa.order_rows["P-1"] = [_row("P-1", "new")]
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == []
    assert "L-AAA" in state["open_positions"]
    assert state["open_positions"]["L-AAA"]["status"] == "pending_fill"
    assert state["gross_exposure_dollars"] == 4000.0
    assert not any(e["event_type"] == "pending_fill_expired"
                   for e in _ledger_events(tmp_path))


def test_janitor_retains_lot_when_cancel_errors_and_probe_fails(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.cancel_results["P-1"] = RuntimeError("connection reset")
    # No order_rows entry → fetch_order returns None (probe failed).
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == []
    assert "L-AAA" in state["open_positions"]


def test_janitor_adopts_when_cancel_errors_but_parent_filled(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.cancel_results["P-1"] = {"status": "error", "http_status": 500}
    oa.order_rows["P-1"] = [_row("P-1", "filled", 400, 10.0)]
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == []
    assert state["open_positions"]["L-AAA"]["status"] == "filled"


def test_janitor_confirmed_cancel_drops_and_restores_exposure(tmp_path):
    """Regression: the pre-fix happy path is preserved."""
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.order_rows["P-1"] = [_row("P-1", "canceled")]
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["AAA"]
    assert state["open_positions"] == {}
    assert state["gross_exposure_dollars"] == 0.0
    assert any(e["event_type"] == "pending_fill_expired"
               for e in _ledger_events(tmp_path))


def test_janitor_not_found_after_cancel_accept_drops(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"gross_exposure_dollars": 4000.0,
             "open_positions": {"L-AAA": _pending_lot()}}
    oa = ScriptedOA()
    oa.order_rows["P-1"] = [{"_status": "not_found"}]
    out = v2.expire_stale_pending_fills(
        state, cfg, oa_client=oa, api_key="k", http=None, now_utc=_NOW,
    )
    assert out == ["AAA"]
    assert state["open_positions"] == {}
