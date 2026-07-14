"""Fix Phase 1 — GET /api/v2/orders pagination + ``limit`` passthrough.

Translator level: ``AlpacaOrderTranslator.list_orders_via_token`` must
paginate past Alpaca's 500-row page cap (asc + ``after`` cursor) and
return rows newest-first. Route level: the optional ``limit`` query
param reaches translators that accept it and is dropped (TypeError
retry) for translators that don't.
"""
from __future__ import annotations

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from services.broker_translator_registry import (
    clear_registry_for_tests,
    register_broker_translator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _paper_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _row(i: int) -> dict:
    return {
        "id": f"O-{i}",
        "status": "filled",
        "submitted_at": f"2026-07-14T13:{i:02d}:00Z",
    }


def _translator_with(handler) -> tuple[AlpacaOrderTranslator, httpx.Client]:
    auth = _paper_auth()
    client = httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )
    return AlpacaOrderTranslator(auth=auth, client=client), client


# ---- translator pagination ----------------------------------------------------


def test_list_orders_paginates_and_sorts_desc():
    rows = [_row(i) for i in range(8)]
    pages = [rows[0:3], rows[3:6], rows[6:8]]
    captured: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v2/orders"
        params = dict(req.url.params)
        captured.append(params)
        assert params["direction"] == "asc"
        assert params["limit"] == "3"
        after = params.get("after")
        if after is None:
            return httpx.Response(200, json=pages[0])
        if after == pages[0][-1]["submitted_at"]:
            return httpx.Response(200, json=pages[1])
        if after == pages[1][-1]["submitted_at"]:
            return httpx.Response(200, json=pages[2])
        return httpx.Response(200, json=[])

    tr, client = _translator_with(handler)
    out = tr.list_orders_via_token("tok", status="all", limit=3)
    client.close()

    # All 8 rows collected across 3 pages, newest first.
    assert [r["id"] for r in out] == [f"O-{i}" for i in reversed(range(8))]
    assert len(captured) == 3
    assert "after" not in captured[0]
    assert captured[1]["after"] == "2026-07-14T13:02:00Z"
    assert captured[2]["after"] == "2026-07-14T13:05:00Z"


def test_list_orders_single_short_page_no_cursor():
    captured: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(dict(req.url.params))
        return httpx.Response(200, json=[_row(0), _row(1)])

    tr, client = _translator_with(handler)
    out = tr.list_orders_via_token("tok", status="open", limit=5)
    client.close()
    assert len(out) == 2
    assert len(captured) == 1


def test_list_orders_limit_clamped_to_alpaca_max():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.update(dict(req.url.params))
        return httpx.Response(200, json=[_row(0)])

    tr, client = _translator_with(handler)
    out = tr.list_orders_via_token("tok", status="all", limit=9999)
    client.close()
    assert captured["limit"] == "500"
    assert len(out) == 1


def test_list_orders_page_cap_stops_runaway(caplog):
    """A broker bug returning full pages forever stops at 20 pages."""
    import logging

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row(0)])  # always "full" at limit=1

    tr, client = _translator_with(handler)
    with caplog.at_level(logging.WARNING):
        out = tr.list_orders_via_token("tok", status="all", limit=1)
    client.close()
    assert len(out) == 20
    assert any("pagination cap" in r.message for r in caplog.records)


# ---- route limit passthrough ---------------------------------------------------


class _StubTranslatorWithLimit:
    broker_code = "alpaca"

    def __init__(self):
        self.calls: list[dict] = []

    def list_orders_via_token(self, auth_token, *, status="open", limit=500):
        self.calls.append({"status": status, "limit": limit})
        return [{"id": "X-1", "status": "filled"}]


class _StubTranslatorNoLimit:
    broker_code = "alpaca"

    def __init__(self):
        self.calls: list[dict] = []

    def list_orders_via_token(self, auth_token, *, status="open"):
        self.calls.append({"status": status})
        return [{"id": "Y-1", "status": "new"}]


def _install_fake_auth(monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.orders.resolve_auth",
        lambda: ("tok", "alpaca", None),
    )


def test_route_forwards_limit(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    stub = _StubTranslatorWithLimit()
    register_broker_translator(stub)
    resp = flask_app.test_client().get("/api/v2/orders?status=all&limit=1000")
    assert resp.status_code == 200, resp.get_json()
    assert stub.calls == [{"status": "all", "limit": 1000}]
    assert resp.get_json()["data"]["count"] == 1


def test_route_retries_without_limit_for_older_translators(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    stub = _StubTranslatorNoLimit()
    register_broker_translator(stub)
    resp = flask_app.test_client().get("/api/v2/orders?status=all&limit=50")
    assert resp.status_code == 200, resp.get_json()
    assert stub.calls == [{"status": "all"}]


def test_route_no_limit_param_keeps_translator_default(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    stub = _StubTranslatorWithLimit()
    register_broker_translator(stub)
    resp = flask_app.test_client().get("/api/v2/orders?status=all")
    assert resp.status_code == 200, resp.get_json()
    assert stub.calls == [{"status": "all", "limit": 500}]


def test_route_rejects_non_integer_limit(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    register_broker_translator(_StubTranslatorWithLimit())
    resp = flask_app.test_client().get("/api/v2/orders?limit=abc")
    assert resp.status_code == 400


def test_route_clamps_limit_bounds(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    stub = _StubTranslatorWithLimit()
    register_broker_translator(stub)
    client = flask_app.test_client()
    client.get("/api/v2/orders?limit=999999")
    client.get("/api/v2/orders?limit=0")
    assert [c["limit"] for c in stub.calls] == [10000, 1]
