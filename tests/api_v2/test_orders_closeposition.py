"""POST /api/v2/orders/closeposition — single-symbol and close-all paths.

Documented Phase 8-bis migration target. Translator hook
``close_position_via_token`` lives on the broker translator;
Alpaca implementation maps onto DELETE /v2/positions/<symbol>
(single) and DELETE /v2/positions (all).
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


def test_closeposition_single_symbol(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/positions/AAPL":
            captured["url"] = str(req.url)
            captured["params"] = dict(req.url.params)
            return httpx.Response(200, json={
                "id": "close-order-1", "status": "accepted",
                "symbol": "AAPL", "qty": "10", "side": "sell",
            })
        return httpx.Response(404, json={"message": "no route"})

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition",
        json={"apikey": "x",
              "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"}},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["status"] == "submitted"
    assert body["instrument"]["canonical_symbol"] == "AAPL"
    assert body["broker_response"]["status"] == "success"
    assert body["broker_response"]["data"]["id"] == "close-order-1"


def test_closeposition_all(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/positions":
            captured["url"] = str(req.url)
            return httpx.Response(207, json=[
                {"symbol": "AAPL", "status": 200, "body": {"id": "ord-1"}},
                {"symbol": "MSFT", "status": 200, "body": {"id": "ord-2"}},
            ])
        return httpx.Response(404, json={"message": "no route"})

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    # No instrument body → close all
    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition", json={"apikey": "x"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["status"] == "submitted"
    assert "instrument" not in body
    data = body["broker_response"]["data"]
    assert isinstance(data, list) and len(data) == 2


def test_closeposition_partial_qty(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/positions/AAPL":
            captured["params"] = dict(req.url.params)
            return httpx.Response(200, json={"id": "partial-1", "qty": "5"})
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition",
        json={"apikey": "x",
              "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
              "qty": "5"},
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    # Alpaca should have received qty=5 as a query param.
    assert captured.get("params", {}).get("qty") == "5"


def test_closeposition_unresolvable_instrument_returns_404(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()  # only AAPL seeded
    seed_alpaca_rules()
    auth = _paper_auth()
    register_broker_translator(AlpacaOrderTranslator(
        auth=auth, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    ))
    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition",
        json={"apikey": "x",
              "instrument": {"venue_code": "XNAS", "canonical_symbol": "ZZZNOTREAL"}},
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "instrument_not_resolvable"


def test_closeposition_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition", json={"apikey": "x"},
    )
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_closeposition_alpaca_4xx_surfaces_alpaca_code(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/positions/AAPL":
            return httpx.Response(404, json={
                "code": 40410000,
                "message": "position not found for symbol AAPL",
            })
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/orders/closeposition",
        json={"apikey": "x",
              "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"}},
    )
    client.close()
    assert resp.status_code == 502
    msg = resp.get_json()["error"]["message"]
    assert "40410000" in msg
    assert "position not found" in msg
