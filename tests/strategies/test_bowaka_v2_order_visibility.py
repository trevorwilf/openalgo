"""Fix Phase 1 — order visibility.

Covers:
- ``bowaka_v2_openalgo_client.fetch_order`` (200 / 404 / network error),
- ``fetch_all_orders`` limit param,
- ``poll_fills_v2`` per-id fallback for tracked ids absent from the
  bulk order list (miss counters, direct fetch, per-tick cap,
  cleanup after closure),
- ``reconcile_with_broker`` qty-mismatch warning + protection event.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest

import bowaka_v2_openalgo_client as oa
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
                  "max_hold_days": 2},
        "logging": {"log_protection_state": True},
    }


# ---- client: fetch_order / fetch_all_orders ---------------------------------


def _client_with(handler) -> httpx.Client:
    return oa.make_http_client(
        "http://oa.test", transport=httpx.MockTransport(handler),
    )


def test_fetch_order_200_returns_row():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v2/orders/ORD-1"
        return httpx.Response(200, json={
            "status": "success",
            "data": {"order": {"id": "ORD-1", "status": "filled"}},
        })
    with _client_with(handler) as http:
        row = oa.fetch_order(http, "k", "ORD-1")
    assert row == {"id": "ORD-1", "status": "filled"}


def test_fetch_order_404_marks_not_found():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "nope"}})
    with _client_with(handler) as http:
        row = oa.fetch_order(http, "k", "GONE")
    assert row == {"_status": "not_found"}


def test_fetch_order_network_error_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)
    with _client_with(handler) as http:
        assert oa.fetch_order(http, "k", "ORD-1") is None


def test_fetch_order_5xx_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"message": "bad"}})
    with _client_with(handler) as http:
        assert oa.fetch_order(http, "k", "ORD-1") is None


def test_fetch_order_empty_id_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected for empty id")
    with _client_with(handler) as http:
        assert oa.fetch_order(http, "k", "") is None


def test_fetch_all_orders_sends_status_all_and_limit():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(dict(req.url.params))
        return httpx.Response(200, json={"data": {"orders": [{"id": "X"}]}})
    with _client_with(handler) as http:
        rows = oa.fetch_all_orders(http, "k")
    assert rows == [{"id": "X"}]
    assert captured == {"status": "all", "limit": "1000"}


# ---- poll_fills_v2 per-id fallback -------------------------------------------


class FakeOA:
    """oa_client surrogate with scriptable bulk + per-id order rows."""

    def __init__(self):
        self.bulk_rows: list[dict] = []
        self.order_rows: dict[str, dict | None] = {}
        self.fetch_order_calls: list[str] = []

    def fetch_all_orders(self, http, api_key):
        return list(self.bulk_rows)

    def fetch_order(self, http, api_key, order_id):
        self.fetch_order_calls.append(order_id)
        return self.order_rows.get(order_id)

    def fetch_positions(self, http, api_key):
        return []


def _bracketed_lot(symbol="AAA", link_id="L-1"):
    return {
        "symbol": symbol, "qty": 100, "status": "filled",
        "link_id": link_id, "entry_price": 10.0,
        "entry_timestamp": "2026-07-10T14:00:00Z",
        "recorded_exposure": 1000.0,
        "child_order_ids": {"target": f"T-{link_id}",
                             "stop": f"S-{link_id}"},
        "target_price": 11.0, "stop_price": 9.0,
        "parent_order_id": f"P-{link_id}",
        "parent_fill_processed": True,
    }


def test_poll_fills_direct_fetch_after_two_misses_books_closure(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "open_positions": {"L-1": _bracketed_lot()},
        "gross_exposure_dollars": 1000.0,
    }
    fake = FakeOA()  # bulk list never shows the children

    # Tick 1: children missed once — no direct fetch yet.
    events = v2.poll_fills_v2(
        state, cfg, oa_client=fake, api_key="k", http=None,
    )
    assert events == []
    assert fake.fetch_order_calls == []
    assert state["order_poll_misses"] == {"T-L-1": 1, "S-L-1": 1}

    # Tick 2: two consecutive misses — direct fetch kicks in. The
    # target reports FILLED; the stop is gone (OCO pair died).
    fake.order_rows["T-L-1"] = {
        "id": "T-L-1", "status": "filled",
        "filled_qty": 100, "filled_avg_price": 11.2,
    }
    fake.order_rows["S-L-1"] = {"_status": "not_found"}
    events = v2.poll_fills_v2(
        state, cfg, oa_client=fake, api_key="k", http=None,
    )
    assert sorted(fake.fetch_order_calls) == ["S-L-1", "T-L-1"]
    assert len(events) == 1
    assert events[0]["role"] == "target"
    assert events[0]["status"] == "FILLED"

    closed = v2.process_fill_events_v2(events, state, cfg)
    assert len(closed) == 1
    assert closed[0]["reason"] == "target_hit"
    assert closed[0]["exit_price"] == 11.2
    assert "L-1" not in state["open_positions"]
    # The unresolved stop keeps its miss counter for later retries.
    assert state["order_poll_misses"] == {"S-L-1": 2}


def test_poll_fills_miss_counters_cleaned_after_close(tmp_path):
    cfg = _cfg(tmp_path)
    # Keep a second (childless) lot so the book stays non-empty and
    # the poll actually runs its cleanup pass.
    other = _bracketed_lot(symbol="BBB", link_id="L-2")
    other["child_order_ids"] = {"target": "", "stop": ""}
    state = {
        "open_positions": {"L-2": other},
        "order_poll_misses": {"T-L-1": 4, "S-L-1": 4},
        "order_poll_warned": {"S-L-1": "2026-07-14"},
        "gross_exposure_dollars": 1000.0,
    }
    fake = FakeOA()
    v2.poll_fills_v2(state, cfg, oa_client=fake, api_key="k", http=None)
    # L-1's ids are no longer tracked — counters and warn marks drop.
    assert state["order_poll_misses"] == {}
    assert state["order_poll_warned"] == {}
    assert fake.fetch_order_calls == []


def test_poll_missing_orders_caps_and_round_robins(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "open_positions": {},
        "order_poll_misses": {f"O-{i}": 2 for i in range(7)},
    }
    idx = {f"O-{i}": ("L-x", "target") for i in range(7)}
    fake = FakeOA()  # every fetch returns None → misses retained
    v2._poll_missing_orders(
        state, cfg, idx=idx, seen=set(), events=[],
        oa_client=fake, api_key="k", http=None,
    )
    assert len(fake.fetch_order_calls) == 5
    assert fake.fetch_order_calls == [f"O-{i}" for i in range(5)]
    # Next tick rotates to the not-yet-fetched ids first.
    v2._poll_missing_orders(
        state, cfg, idx=idx, seen=set(), events=[],
        oa_client=fake, api_key="k", http=None,
    )
    assert fake.fetch_order_calls[5:7] == ["O-5", "O-6"]


def test_poll_fills_no_fallback_without_fetch_order(tmp_path):
    """A legacy oa_client without fetch_order degrades gracefully."""
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _bracketed_lot()}}

    class LegacyOA:
        def fetch_all_orders(self, http, api_key):
            return []

    for _ in range(3):
        events = v2.poll_fills_v2(
            state, cfg, oa_client=LegacyOA(), api_key="k", http=None,
        )
    assert events == []
    assert state["order_poll_misses"] == {"T-L-1": 3, "S-L-1": 3}


# ---- reconcile qty comparison -------------------------------------------------


class FakeReconcileOA:
    def __init__(self, positions):
        self._positions = positions

    def fetch_positions(self, http, api_key):
        return self._positions

    def fetch_all_orders(self, http, api_key):
        return []


def _protection_events(tmp_path) -> list[dict]:
    p = tmp_path / "protection_events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_reconcile_qty_mismatch_warns_and_emits(tmp_path, caplog):
    cfg = _cfg(tmp_path)
    state = {"open_positions": {"L-1": _bracketed_lot("AAA")}}
    fake = FakeReconcileOA([{"symbol": "AAA", "qty": 60}])
    with caplog.at_level(logging.WARNING):
        rc = v2.reconcile_with_broker(
            state, cfg, oa_client=fake, api_key="k", http=None,
        )
    assert rc is None  # mismatch warns — never halts
    assert any("qty mismatch" in r.message for r in caplog.records)
    mismatches = [e for e in _protection_events(tmp_path)
                  if e.get("event") == "qty_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["state_qty"] == 100.0
    assert mismatches[0]["broker_qty"] == 60.0


def test_reconcile_matching_qty_is_silent(tmp_path, caplog):
    cfg = _cfg(tmp_path)
    # A pending_fill lot must NOT count toward the state qty.
    pending = _bracketed_lot("AAA", link_id="L-2")
    pending["status"] = "pending_fill"
    pending["qty"] = 40
    state = {"open_positions": {
        "L-1": _bracketed_lot("AAA"), "L-2": pending,
    }}
    fake = FakeReconcileOA([{"symbol": "AAA", "qty": 100}])
    with caplog.at_level(logging.WARNING):
        rc = v2.reconcile_with_broker(
            state, cfg, oa_client=fake, api_key="k", http=None,
        )
    assert rc is None
    assert not any("qty mismatch" in r.message for r in caplog.records)
    assert [e for e in _protection_events(tmp_path)
            if e.get("event") == "qty_mismatch"] == []
