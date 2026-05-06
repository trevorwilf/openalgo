"""GET /api/v2/trades — Phase 8-bis migration test.

Pins the contract for the new tradebook route:
* dispatches to translator's list_trades_via_token
* fail-closed (501) when translator hasn't implemented the hook
* fail-closed (503) when translator isn't registered
* page_size validation (1..500)
* date param flows through to Alpaca's /v2/account/activities query
* Alpaca structured 4xx surfaces the alpaca code through broker_error
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
    monkeypatch.setattr(
        "restx_api.v2.trades.resolve_auth",
        lambda: ("fake-token", "alpaca", None),
    )


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


def test_trades_dispatches_to_alpaca(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/account/activities":
            captured["url"] = str(req.url)
            captured["params"] = dict(req.url.params)
            return httpx.Response(200, json=[
                {"id": "act-1", "activity_type": "FILL",
                 "transaction_time": "2026-05-06T13:35:00Z",
                 "type": "fill", "price": "281.41", "qty": "1",
                 "side": "buy", "symbol": "AAPL", "order_id": "ord-1"},
                {"id": "act-2", "activity_type": "FILL",
                 "transaction_time": "2026-05-06T13:36:00Z",
                 "type": "fill", "price": "281.55", "qty": "1",
                 "side": "sell", "symbol": "AAPL", "order_id": "ord-2"},
            ])
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get("/api/v2/trades", query_string={"apikey": "x"})
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["count"] == 2
    assert body["trades"][0]["symbol"] == "AAPL"
    # default page_size flows through
    assert captured["params"].get("activity_types") == "FILL"
    assert captured["params"].get("page_size") == "100"


def test_trades_date_param_flows_through(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/account/activities":
            captured["params"] = dict(req.url.params)
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get(
        "/api/v2/trades",
        query_string={"apikey": "x", "date": "2026-05-06", "page_size": "50"},
    )
    client.close()
    assert resp.status_code == 200
    assert captured["params"].get("date") == "2026-05-06"
    assert captured["params"].get("page_size") == "50"


def test_trades_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().get("/api/v2/trades", query_string={"apikey": "x"})
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_trades_flag_off_returns_503(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_ALPACA", raising=False)
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().get("/api/v2/trades", query_string={"apikey": "x"})
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "promoted_lane_required"


def test_trades_bad_page_size_returns_400(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get(
        "/api/v2/trades", query_string={"apikey": "x", "page_size": "9999"},
    )
    client.close()
    assert resp.status_code == 400


def test_trades_alpaca_4xx_surfaces_alpaca_code(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/account/activities":
            return httpx.Response(429, json={
                "code": 42929000,
                "message": "rate limit exceeded",
            })
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get("/api/v2/trades", query_string={"apikey": "x"})
    client.close()
    assert resp.status_code == 502
    msg = resp.get_json()["error"]["message"]
    assert "42929000" in msg
    assert "rate limit" in msg
