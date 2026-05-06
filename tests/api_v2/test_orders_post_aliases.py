"""POST aliases for cancel and cancel-all — Phase 8-bis migration targets.

These mirror the DELETE-shaped paths so clients that can't send DELETE
(some no-code platforms, older HTTP toolchains) can still cancel orders
through the v2 surface. Translator hooks are reused verbatim — behavior
is bit-identical with the DELETE paths.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from broker.alpaca.sync.seed_rules import seed_alpaca_rules
from database.instruments_repo import (
    BrokerMapRow, broker_map_upsert_many, instruments_create, venues_upsert,
)
from services.broker_translator_registry import (
    clear_registry_for_tests, register_broker_translator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _paper_auth():
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _install_fake_auth(monkeypatch):
    monkeypatch.setattr("restx_api.v2.orders.resolve_auth",
                        lambda: ("fake-token", "alpaca", None))


def _seed_aapl():
    venues_upsert("XNAS", market_family="US_STOCK", country_code="US",
                   base_currency="USD", timezone_name="America/New_York")
    aapl = instruments_create(
        venue_code="XNAS", canonical_symbol="AAPL",
        asset_class="EQUITY", instrument_kind="CASH",
        tick_size=Decimal("0.01"), quantity_precision=9, currency="USD",
    )
    broker_map_upsert_many(
        broker_code="alpaca", venue_code="XNAS", sync_version=1,
        rows=[BrokerMapRow(external_symbol="AAPL",
                           external_token="alpaca-aapl-id",
                           instrument_id=aapl.instrument_id)],
    )


def test_cancelall_post_alias(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/orders":
            captured["url"] = str(req.url)
            return httpx.Response(207, json=[
                {"id": "ord-1", "status": 200},
                {"id": "ord-2", "status": 422, "body": {"reason": "stale"}},
            ])
        return httpx.Response(404, json={"message": "no route"})

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/cancelall", json={"apikey": "x"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["summary"]["canceled_count"] == 1
    assert body["summary"]["failed_count"] == 1
    assert body["canceled"] == [{"order_id": "ord-1"}]
    assert body["failed"][0]["order_id"] == "ord-2"


def test_cancelall_post_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().post("/api/v2/orders/cancelall",
                                          json={"apikey": "x"})
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_cancel_post_alias(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path.startswith("/v2/orders/"):
            captured["url"] = str(req.url)
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "no route"})

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-abc/cancel", json={"apikey": "x"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["order_id"] == "ord-abc"
    assert body["status"] == "canceled"
    # Confirm the translator hit the right native URL.
    assert "/v2/orders/ord-abc" in captured["url"]


def test_cancel_post_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().post(
        "/api/v2/orders/ord-1/cancel", json={"apikey": "x"},
    )
    assert resp.status_code == 503
