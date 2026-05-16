"""Phase 6 — event-driven order stream + poll reconciliation.

Covers:
* Streaming disabled in cfg: OrderStreamClient is never instantiated;
  polling behavior is unchanged (no regression).
* Stream event for a parent fill produces exactly one entry_fill.
* Same parent fill arriving via stream THEN poll is idempotent.
* Poll surfacing an order the stream didn't see increments
  missed_events_recovered_by_poll.
* After max_consecutive_failures the client stops trying and
  emits a stream_failed ledger event.
* stream_health events include populated lag_seconds.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import bowaka_strategy as bw


def _mk_parent_fill_row(order_id: str, ticker: str = "ASPI",
                        filled_qty: int = 10,
                        filled_avg: float = 5.80) -> dict:
    return {
        "id": order_id,
        "order_id": order_id,
        "status": "filled",
        "native_status": "filled",
        "canonical_status": "FILLED",
        "filled_qty": str(filled_qty),
        "filled_avg_price": str(filled_avg),
    }


def _seed_pending_position(cfg, ticker: str = "ASPI",
                            parent_id: str = "P-1") -> tuple[bw.State, Path]:
    state = bw.blank_state()
    state["open_positions"][ticker] = {
        "status": "pending_entry",
        "parent_order_id": parent_id,
        "link_id": f"BOWAKA-{ticker}-1",
        "qty": 10,
        "entry_price": None,
        "venue_code": "XNAS",
        "entry_timestamp": "2026-05-15T13:30:00+00:00",
    }
    state_path = Path(cfg["paths"]["state_path"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    bw.save_state(state, state_path)
    return state, state_path


def test_streaming_disabled_no_client_no_regression(
    cfg_with_paths,
) -> None:
    state, state_path = _seed_pending_position(cfg_with_paths)

    polled_calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/api/v2/orders":
            polled_calls.append(req.url.path)
            return httpx.Response(200, json={
                "data": {"orders": [_mk_parent_fill_row("P-1")]},
            })
        return httpx.Response(404, json={"error": "no-route"})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    events = bw.poll_fills(
        state, http, "k",
        state_path=state_path, cfg=cfg_with_paths,
    )
    # One parent fill emitted via the legacy poll path.
    parent_fills = [e for e in events if e.role == "parent"]
    assert len(parent_fills) == 1
    assert polled_calls == ["/api/v2/orders"]


def test_stream_event_processed_through_handle_parent_fill(
    cfg_with_paths,
) -> None:
    state, state_path = _seed_pending_position(cfg_with_paths)

    def handler(req: httpx.Request) -> httpx.Response:
        # Empty poll — stream is the source of truth here.
        if req.method == "GET" and req.url.path == "/api/v2/orders":
            return httpx.Response(200, json={"data": {"orders": []}})
        return httpx.Response(404, json={"error": "no-route"})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    sc.start()
    sc.push_test_event(_mk_parent_fill_row("P-1"))

    events = bw.poll_fills(
        state, http, "k",
        state_path=state_path, cfg=cfg_with_paths,
        stream_client=sc,
    )
    parent_fills = [e for e in events if e.role == "parent"]
    assert len(parent_fills) == 1
    assert state["open_positions"]["ASPI"]["status"] == "filled"


def test_stream_then_poll_idempotent(cfg_with_paths) -> None:
    state, state_path = _seed_pending_position(cfg_with_paths)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/api/v2/orders":
            return httpx.Response(200, json={
                "data": {"orders": [_mk_parent_fill_row("P-1")]},
            })
        return httpx.Response(404, json={"error": "no-route"})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    sc.start()
    sc.push_test_event(_mk_parent_fill_row("P-1"))

    events = bw.poll_fills(
        state, http, "k",
        state_path=state_path, cfg=cfg_with_paths,
        stream_client=sc,
    )
    # Stream handled it first; the poll's row is a duplicate.
    parent_fills = [e for e in events if e.role == "parent"]
    assert len(parent_fills) == 1


def test_poll_recovers_missed_event_counter(cfg_with_paths) -> None:
    state, state_path = _seed_pending_position(cfg_with_paths)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/api/v2/orders":
            return httpx.Response(200, json={
                "data": {"orders": [_mk_parent_fill_row("P-1")]},
            })
        return httpx.Response(404, json={"error": "no-route"})

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://x",
    )
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    sc.start()
    # Stream sees NOTHING. Poll surfaces P-1 — counts as recovered.
    bw.poll_fills(
        state, http, "k",
        state_path=state_path, cfg=cfg_with_paths,
        stream_client=sc,
    )
    stats = sc.stats()
    assert stats["missed_events_recovered_by_poll"] == 1


def test_stream_failed_after_5_consecutive_failures(cfg_with_paths) -> None:
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    for _i in range(5):
        sc.record_failure()
    assert sc.stopped is True

    ledger = bw._ledger_path(cfg_with_paths)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    failed = [e for e in events if e["event_type"] == "stream_failed"]
    assert len(failed) == 1


def test_stream_health_populates_lag_seconds(cfg_with_paths) -> None:
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    sc.start()
    sc.push_test_event(_mk_parent_fill_row("P-1"))
    sc.drain()
    stats = sc.stats()
    assert stats["connected"] is True
    assert stats["last_event_at"] is not None
    assert stats["lag_seconds"] is not None and stats["lag_seconds"] >= 0


def test_emit_stream_health_writes_ledger(cfg_with_paths) -> None:
    sc = bw.OrderStreamClient(cfg_with_paths, "k")
    sc.start()
    sc.push_test_event(_mk_parent_fill_row("P-1"))
    sc.drain()
    bw.emit_stream_health(cfg_with_paths, sc)
    ledger = bw._ledger_path(cfg_with_paths)
    events = [
        json.loads(l) for l in ledger.read_text().splitlines() if l.strip()
    ]
    health = [e for e in events if e["event_type"] == "stream_health"]
    assert len(health) == 1
    assert "lag_seconds" in health[0]["payload"]
    assert "missed_events_recovered_by_poll" in health[0]["payload"]
