"""Fix Phase 5 — fill completeness.

Covers:
- partially-filled-then-dead OCO children: partial closure booked for
  the executed shares, exposure released proportionally, both child
  ids cleared, bracket re-attached to the remainder; duplicate DEAD
  echoes don't double-book; remaining 0 routes through a full close;
  stop-out counters bump only on full stop closes,
- tail_new_events torn-line / truncation / malformed-line semantics.
"""
from __future__ import annotations

import json

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
        "exits": {"stop_pct": 0.05, "target_pct": 0.10,
                  "max_hold_days": 2, "oco_time_in_force": "GTC"},
        "logging": {"log_protection_state": True},
    }


def _closures(tmp_path) -> list[dict]:
    p = tmp_path / "daily_summary.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _lot(qty=100, exposure=1000.0):
    return {
        "symbol": "AAA", "qty": qty, "status": "filled",
        "link_id": "L-1", "entry_price": 10.0,
        "entry_timestamp": "2026-07-10T14:00:00Z",
        "recorded_exposure": exposure,
        "child_order_ids": {"target": "T-1", "stop": "S-1"},
        "target_price": 11.0, "stop_price": 9.5,
        "parent_order_id": "P-1", "parent_fill_processed": True,
        "venue_code": "XNAS",
    }


def _dead_child_ev(role="target", oid="T-1", filled_qty=40, fap=11.0,
                    status="CANCELED"):
    return {
        "symbol": "AAA", "pos_id": "L-1", "order_id": oid,
        "role": role, "status": status, "filled_qty": filled_qty,
        "filled_avg_price": fap, "raw": {},
    }


class ReattachOA:
    def __init__(self):
        self.oco_calls: list[dict] = []

    def submit_oco_bracket(self, http, api_key, *, venue_code, symbol,
                            qty, target_price, stop_price, link_id,
                            time_in_force="GTC"):
        self.oco_calls.append({"symbol": symbol, "qty": qty})
        return {
            "_http_status": 200,
            "data": {"native_response": {
                "id": "OCO-2",
                "legs": [
                    {"id": "T-2", "order_type": "limit"},
                    {"id": "S-2", "order_type": "stop"},
                ],
            }},
        }


# ---- partial-dead children -----------------------------------------------------


def test_partial_dead_target_books_partial_and_rebrackets(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _lot()},
             "gross_exposure_dollars": 1000.0,
             "daily_realized_pnl_strategy": 0.0,
             "cumulative_realized_pnl_strategy": 0.0}
    ev = _dead_child_ev(filled_qty=40, fap=11.0)
    out = v2.process_fill_events_v2([ev], state, cfg)
    assert len(out) == 1
    rec = out[0]
    assert rec["reason"] == "target_hit_partial"
    assert rec["qty"] == 40
    assert rec["exit_price"] == 11.0
    assert rec["realized_pnl"] == pytest.approx(40 * 1.0)
    assert rec["partial"] is True
    assert rec["remaining_qty"] == 60

    pos = state["open_positions"]["L-1"]
    assert pos["qty"] == 60
    assert pos["status"] == "filled"
    # Both ids cleared — the OCO pair dies together at the broker.
    assert pos["child_order_ids"] == {"target": "", "stop": ""}
    # Exposure released proportionally: 1000 * 40/100 = 400 off.
    assert pos["recorded_exposure"] == pytest.approx(600.0)
    assert state["gross_exposure_dollars"] == pytest.approx(600.0)
    assert state["daily_realized_pnl_strategy"] == pytest.approx(40.0)
    assert state["cumulative_realized_pnl_strategy"] == pytest.approx(40.0)
    # PnL is ledgered as a closure record.
    assert [c["reason"] for c in _closures(tmp_path)] \
        == ["target_hit_partial"]

    # The re-attach sweep brackets the remaining 60.
    oa = ReattachOA()
    attached = v2.submit_pending_oco_children_v2(
        state, cfg, oa_client=oa, api_key="k", http=None,
    )
    assert attached == ["AAA"]
    assert oa.oco_calls == [{"symbol": "AAA", "qty": 60}]
    assert pos["child_order_ids"] == {"target": "T-2", "stop": "S-2"}


def test_partial_dead_covering_full_qty_routes_full_close(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _lot(qty=100)},
             "gross_exposure_dollars": 1000.0}
    ev = _dead_child_ev(role="stop", oid="S-1", filled_qty=100, fap=9.5)
    out = v2.process_fill_events_v2([ev], state, cfg)
    assert len(out) == 1
    assert out[0]["reason"] == "stop_hit"       # full close, not partial
    assert "L-1" not in state["open_positions"]
    # Full stop close bumps the stop-out circuit breakers.
    assert state["daily_stopout_count"] == 1
    assert state["consecutive_stopout_count"] == 1


def test_duplicate_dead_echo_does_not_double_book(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _lot()},
             "gross_exposure_dollars": 1000.0}
    ev = _dead_child_ev(filled_qty=40, fap=11.0)
    out1 = v2.process_fill_events_v2([ev], state, cfg)
    assert len(out1) == 1
    # The same DEAD echo replays (e.g. next bulk poll).
    out2 = v2.process_fill_events_v2([ev], state, cfg)
    assert out2 == []
    assert state["open_positions"]["L-1"]["qty"] == 60
    assert len(_closures(tmp_path)) == 1


def test_partial_dead_stop_does_not_bump_stopout_counters(tmp_path):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _lot()},
             "gross_exposure_dollars": 1000.0}
    ev = _dead_child_ev(role="stop", oid="S-1", filled_qty=40, fap=9.5)
    out = v2.process_fill_events_v2([ev], state, cfg)
    assert out[0]["reason"] == "stop_hit_partial"
    assert state.get("daily_stopout_count", 0) == 0
    assert state.get("consecutive_stopout_count", 0) == 0


def test_partial_dead_without_price_defers(tmp_path):
    cfg = _cfg(tmp_path)
    lot = _lot()
    lot.pop("target_price")               # no stored fallback price
    state = {"open_positions": {"L-1": lot},
             "gross_exposure_dollars": 1000.0}
    ev = _dead_child_ev(filled_qty=40, fap=None)
    out = v2.process_fill_events_v2([ev], state, cfg)
    assert out == []
    pos = state["open_positions"]["L-1"]
    assert pos["qty"] == 100               # nothing booked yet
    assert pos.get("child_partial_processed", {}).get("target") is None
    assert pos["exit_price_pending"] is True
    # Echo with a usable price arrives — the retry books it.
    ev2 = _dead_child_ev(filled_qty=40, fap=11.1)
    out2 = v2.process_fill_events_v2([ev2], state, cfg)
    assert len(out2) == 1
    assert out2[0]["exit_price"] == 11.1


def test_poll_emits_dead_partial_child_event(tmp_path):
    """End-to-end: the bulk poll surfaces a DEAD+partial child row."""
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _lot()},
             "gross_exposure_dollars": 1000.0}

    class OA:
        def fetch_all_orders(self, http, api_key):
            return [{"id": "T-1", "status": "canceled",
                     "filled_qty": 40, "filled_avg_price": 11.0}]

        def fetch_order(self, http, api_key, order_id):
            return None

    events = v2.poll_fills_v2(
        state, cfg, oa_client=OA(), api_key="k", http=None,
    )
    assert len(events) == 1
    assert events[0]["role"] == "target"
    assert events[0]["filled_qty"] == 40
    out = v2.process_fill_events_v2(events, state, cfg)
    assert out[0]["reason"] == "target_hit_partial"


# ---- tail_new_events -------------------------------------------------------------


def _line(symbol: str) -> str:
    return json.dumps({"symbol": symbol, "event_type": "candidate_signal"})


def test_tail_torn_line_not_consumed_then_consumed(tmp_path):
    p = tmp_path / "candidate_events.jsonl"
    p.write_text(_line("AAA") + "\n", encoding="utf-8")
    events, off1 = v2.tail_new_events(p, 0)
    assert [e["symbol"] for e in events] == ["AAA"]
    assert off1 == p.stat().st_size

    torn = _line("BBB")
    half = len(torn) // 2
    with open(p, "a", encoding="utf-8") as f:
        f.write(torn[:half])              # scanner mid-append
    events, off2 = v2.tail_new_events(p, off1)
    assert events == []
    assert off2 == off1                    # torn bytes NOT consumed

    with open(p, "a", encoding="utf-8") as f:
        f.write(torn[half:] + "\n")        # append completes
    events, off3 = v2.tail_new_events(p, off2)
    assert [e["symbol"] for e in events] == ["BBB"]
    assert off3 == p.stat().st_size


def test_tail_truncated_file_resets_offset(tmp_path):
    p = tmp_path / "candidate_events.jsonl"
    p.write_text(_line("AAA") + "\n" + _line("BBB") + "\n",
                 encoding="utf-8")
    _events, off = v2.tail_new_events(p, 0)
    # Rotation: the file is rewritten smaller than the stored offset.
    p.write_text(_line("CCC") + "\n", encoding="utf-8")
    events, new_off = v2.tail_new_events(p, off)
    assert [e["symbol"] for e in events] == ["CCC"]
    assert new_off == p.stat().st_size


def test_tail_malformed_complete_line_skipped_offset_advanced(tmp_path):
    p = tmp_path / "candidate_events.jsonl"
    p.write_text(
        _line("AAA") + "\n" + "{not json…\n" + _line("BBB") + "\n",
        encoding="utf-8",
    )
    events, off = v2.tail_new_events(p, 0)
    assert [e["symbol"] for e in events] == ["AAA", "BBB"]
    assert off == p.stat().st_size


def test_tail_missing_file_and_no_new_bytes(tmp_path):
    p = tmp_path / "candidate_events.jsonl"
    assert v2.tail_new_events(p, 123) == ([], 123)
    p.write_text(_line("AAA") + "\n", encoding="utf-8")
    _e, off = v2.tail_new_events(p, 0)
    assert v2.tail_new_events(p, off) == ([], off)
