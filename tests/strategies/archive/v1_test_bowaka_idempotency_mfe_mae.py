"""Phase 3 — parent-fill idempotency + canonical MFE/MAE.

Covers:
* A second poll_fills returning the same parent FILLED row does not
  emit a second entry_fill, does not reset peak/trough, and does not
  change entry_price.
* A FILLED row arriving while status is "exiting" or "closed" is
  silently suppressed; one duplicate_parent_fill_suppressed event is
  emitted; peak_since_entry is unchanged.
* _initialize_peak_trough_once is genuinely once.
* Two back-to-back trigger_time_stop calls for the same reason on
  the same day result in exactly one submit_market_sell.
* canonical_mfe_mae matches a hand-computed expected value.
* ASPI-shaped replay: a parent FILLED row arriving on every poll
  produces one entry_fill, no peak/trough reset, MFE/MAE end equal
  to the path's true high/low.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

import bowaka_strategy as bw


# ---- canonical_mfe_mae ----------------------------------------------


def test_canonical_mfe_mae_hand_check() -> None:
    bars = [
        {"high": 11.0, "low": 9.5, "open": 10.0, "close": 10.5},
        {"high": 12.0, "low": 10.0, "open": 10.5, "close": 11.5},
        {"high": 11.5, "low": 9.0, "open": 11.5, "close": 9.2},
    ]
    out = bw.canonical_mfe_mae(10.0, bars)
    assert out["peak"] == pytest.approx(12.0)
    assert out["trough"] == pytest.approx(9.0)
    assert out["mfe_pct"] == pytest.approx(0.20)
    assert out["mae_pct"] == pytest.approx(-0.10)


def test_canonical_mfe_mae_with_dataframe() -> None:
    df = pd.DataFrame([
        {"high": 11.0, "low": 9.5, "open": 10.0, "close": 10.5},
        {"high": 12.0, "low": 10.0, "open": 10.5, "close": 11.5},
    ])
    out = bw.canonical_mfe_mae(10.0, df)
    assert out["peak"] == pytest.approx(12.0)
    assert out["trough"] == pytest.approx(9.5)


def test_canonical_mfe_mae_zero_entry_returns_zeros() -> None:
    out = bw.canonical_mfe_mae(0.0, [{"high": 1, "low": 0.5}])
    assert out == {"mfe_pct": 0.0, "mae_pct": 0.0, "peak": 0.0, "trough": 0.0}


def test_canonical_mfe_mae_empty_bars_returns_zeros() -> None:
    out = bw.canonical_mfe_mae(10.0, [])
    assert out == {"mfe_pct": 0.0, "mae_pct": 0.0, "peak": 0.0, "trough": 0.0}


def test_canonical_mfe_mae_mid_source() -> None:
    bars = [
        {"open": 10.0, "close": 12.0, "high": 13.0, "low": 9.0},
        {"open": 11.0, "close": 13.0, "high": 14.0, "low": 10.0},
    ]
    out = bw.canonical_mfe_mae(10.0, bars, mark_source="mid")
    # Mid for bar 0 = 11, bar 1 = 12.
    assert out["peak"] == pytest.approx(12.0)
    assert out["trough"] == pytest.approx(10.0)


# ---- _initialize_peak_trough_once -----------------------------------


def test_init_peak_trough_runs_once() -> None:
    pos = {"entry_price": 100.0}
    bw._initialize_peak_trough_once(pos)
    assert pos["peak_since_entry"] == 100.0
    assert pos["trough_since_entry"] == 100.0
    assert pos["mfe_mae_initialized"] is True
    # Simulate price movement and a second call.
    pos["peak_since_entry"] = 120.0
    pos["trough_since_entry"] = 90.0
    bw._initialize_peak_trough_once(pos)
    # No-op — the move is preserved.
    assert pos["peak_since_entry"] == 120.0
    assert pos["trough_since_entry"] == 90.0


# ---- _handle_parent_fill idempotency --------------------------------


def _mk_fill(order_id: str, qty: int, avg: float | None,
             status: str = "FILLED") -> bw.FillEvent:
    return bw.FillEvent(
        ticker="X", order_id=order_id, role="parent",
        status=status, filled_qty=qty, filled_avg_price=avg,
        raw={"id": order_id},
    )


def test_handle_parent_fill_processes_once_only(cfg_with_paths, tmp_path) -> None:
    pos = {
        "status": "pending_entry",
        "parent_order_id": "P-1",
        "link_id": "T-1",
        "qty": 10,
    }
    ev = _mk_fill("P-1", qty=10, avg=10.0)
    dirty1, e1 = bw._handle_parent_fill("X", pos, ev, cfg_with_paths)
    assert dirty1 is True
    assert len(e1) == 1
    # Simulate a price move recorded in peak/trough.
    pos["peak_since_entry"] = 12.0
    pos["trough_since_entry"] = 9.0
    # Second call (e.g., the parent row lingers in /orders?status=all).
    dirty2, e2 = bw._handle_parent_fill("X", pos, ev, cfg_with_paths)
    assert dirty2 is False
    assert e2 == []
    # Peak/trough were preserved.
    assert pos["peak_since_entry"] == 12.0
    assert pos["trough_since_entry"] == 9.0
    # entry_price unchanged.
    assert pos["entry_price"] == 10.0


def test_handle_parent_fill_late_status_emits_suppression_event(
    cfg_with_paths, tmp_path,
) -> None:
    pos = {
        "status": "exiting",
        "parent_order_id": "P-1",
        "link_id": "T-LATE",
        "qty": 10,
        "entry_price": 10.0,
        "peak_since_entry": 11.5,
        "trough_since_entry": 9.5,
        "mfe_mae_initialized": True,
    }
    ev = _mk_fill("P-1", qty=10, avg=10.0)
    dirty, evs = bw._handle_parent_fill("X", pos, ev, cfg_with_paths)
    assert dirty is True
    assert evs == []
    assert pos["peak_since_entry"] == 11.5
    assert pos["trough_since_entry"] == 9.5
    # Ledger has one duplicate_parent_fill_suppressed event.
    ledger = bw._ledger_path(cfg_with_paths)
    suppressed = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
        if json.loads(l).get("event_type") == "duplicate_parent_fill_suppressed"
    ]
    assert len(suppressed) == 1


def test_handle_parent_fill_closed_status_suppressed_same_way(
    cfg_with_paths,
) -> None:
    pos = {
        "status": "closed",
        "parent_order_id": "P-1",
        "link_id": "T-Z",
        "qty": 10,
        "entry_price": 10.0,
        "peak_since_entry": 12.0,
        "trough_since_entry": 9.0,
        "mfe_mae_initialized": True,
    }
    ev = _mk_fill("P-1", qty=10, avg=10.0)
    dirty, _ = bw._handle_parent_fill("X", pos, ev, cfg_with_paths)
    assert dirty is True
    assert pos["peak_since_entry"] == 12.0


# ---- _build_order_index parent indexing restriction -----------------


def test_build_order_index_only_indexes_parent_for_pre_fill() -> None:
    state = bw.blank_state()
    # Position 1: pre-fill (status=pending_entry) — parent INDEXED.
    state["open_positions"]["A"] = {
        "status": "pending_entry",
        "parent_order_id": "PA",
    }
    # Position 2: filled — parent NOT indexed.
    state["open_positions"]["B"] = {
        "status": "filled",
        "parent_order_id": "PB",
        "child_order_ids": {"target": "TB", "stop": "SB"},
    }
    idx = bw._build_order_index(state)
    assert idx.get("PA") == ("A", "parent")
    assert "PB" not in idx
    # Child IDs always indexed.
    assert idx.get("TB") == ("B", "target")
    assert idx.get("SB") == ("B", "stop")


# ---- exit idempotency in trigger_time_stop --------------------------


def test_trigger_time_stop_dedupes_via_ledger_idempotency_key(
    cfg_with_paths, tmp_path, strategy_module,
):
    """Two back-to-back calls with the same (ticker, reason,
    entry_date) MUST submit at most one market-sell."""
    pos = {
        "status": "filled",
        "parent_order_id": "P-1",
        "link_id": "BOWAKA-A-1",
        "qty": 10,
        "entry_price": 10.0,
        "venue_code": "XNAS",
        "entry_timestamp": "2026-05-15T13:30:00+00:00",
    }
    state = strategy_module.blank_state()
    state["open_positions"]["A"] = pos
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    strategy_module.save_state(state, state_path)

    sells: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v2/orders":
            sells.append(req.content.decode("utf-8"))
            return httpx.Response(
                200, json={"data": {"order_id": "EXIT-1"}},
            )
        if req.method == "DELETE":
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404, json={"error": "no-route"})

    http = strategy_module.make_http_client(
        "http://x", transport=httpx.MockTransport(handler),
    )
    strategy_module.trigger_time_stop(
        "A", pos, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
        reason="time_stop",
    )
    # First call submitted one market sell.
    assert len(sells) == 1
    # State is now "exiting"; reset to "filled" to simulate the
    # caller-side guard not catching the second attempt and force
    # the idempotency-key check to act.
    pos["status"] = "filled"
    strategy_module.save_state(state, state_path)
    strategy_module.trigger_time_stop(
        "A", pos, cfg_with_paths, http, "k",
        state=state, state_path=state_path,
        reason="time_stop",
    )
    # No second submission — suppressed by idempotency key.
    assert len(sells) == 1


# ---- ASPI-shaped replay ---------------------------------------------


def _orders_handler_with_lingering_parent(
    parent_order_id: str, filled_qty: int, filled_avg: float,
):
    """Returns a handler that always reports the parent as FILLED
    when /orders?status=all is polled — simulates the bug shape
    where the parent lingers in the broker's all-status window."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/api/v2/orders":
            return httpx.Response(200, json={
                "data": {"orders": [{
                    "id": parent_order_id,
                    "order_id": parent_order_id,
                    "status": "filled",
                    "native_status": "filled",
                    "canonical_status": "FILLED",
                    "filled_qty": str(filled_qty),
                    "filled_avg_price": str(filled_avg),
                }]},
            })
        return httpx.Response(404, json={"error": "no-route"})

    return handler


def test_aspi_replay_parent_fill_idempotent_across_5_polls(
    cfg_with_paths, tmp_path, strategy_module,
):
    pos = {
        "status": "pending_entry",
        "parent_order_id": "P-ASPI",
        "link_id": "BOWAKA-ASPI-1",
        "qty": 643,
        "entry_price": None,
        "venue_code": "XNAS",
        "entry_timestamp": "2026-05-12T13:30:00+00:00",
    }
    state = strategy_module.blank_state()
    state["open_positions"]["ASPI"] = pos
    state_path = Path(cfg_with_paths["paths"]["state_path"])
    strategy_module.save_state(state, state_path)

    transport = httpx.MockTransport(_orders_handler_with_lingering_parent(
        "P-ASPI", filled_qty=643, filled_avg=5.80,
    ))
    http = strategy_module.make_http_client("http://x", transport=transport)

    fills_emitted = 0
    for _i in range(5):
        evs = strategy_module.poll_fills(
            state, http, "k", state_path=state_path,
            cfg=cfg_with_paths,
        )
        for ev in evs:
            if ev.role == "parent" and ev.status == "FILLED":
                fills_emitted += 1
        # Simulate intraday price excursion AFTER the parent fill.
        if _i == 1:
            pos["peak_since_entry"] = 6.50
            pos["trough_since_entry"] = 5.40

    # The parent FILLED row was returned 5 times, but only the FIRST
    # poll produces a parent fill event. Subsequent polls are no-ops.
    assert fills_emitted == 1
    assert pos["parent_fill_processed"] is True
    # MFE/MAE excursion preserved across the bug-replay window.
    assert pos["peak_since_entry"] == 6.50
    assert pos["trough_since_entry"] == 5.40
    assert pos["entry_price"] == 5.80
