"""GET /api/v2/holdings — Phase 8-bis migration test.

Pins the holdings route's contract: dispatches to the translator's
``list_holdings_via_token`` hook, which on Alpaca returns the same
``/v2/positions`` rows (Alpaca doesn't separate intraday vs delivery).
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
        "restx_api.v2.holdings.resolve_auth",
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


def test_holdings_dispatches_to_alpaca_positions(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    captured = {}
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/positions":
            captured["url"] = str(req.url)
            return httpx.Response(200, json=[
                {"symbol": "AAPL", "qty": "10", "avg_entry_price": "281.41",
                 "side": "long", "asset_class": "us_equity"},
            ])
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get("/api/v2/holdings",
                                         query_string={"apikey": "x"})
    client.close()
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["count"] == 1
    assert body["holdings"][0]["symbol"] == "AAPL"


def test_holdings_no_translator_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().get("/api/v2/holdings",
                                         query_string={"apikey": "x"})
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "translator_not_registered"


def test_holdings_flag_off_returns_503(flask_app, monkeypatch):
    monkeypatch.delenv("API_V2_ALPACA", raising=False)
    _install_fake_auth(monkeypatch)
    resp = flask_app.test_client().get("/api/v2/holdings",
                                         query_string={"apikey": "x"})
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "promoted_lane_required"


def test_holdings_alpaca_4xx_surfaces_alpaca_code(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/positions":
            return httpx.Response(401, json={
                "code": 40110000,
                "message": "auth headers missing",
            })
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get("/api/v2/holdings",
                                         query_string={"apikey": "x"})
    client.close()
    assert resp.status_code == 502
    msg = resp.get_json()["error"]["message"]
    assert "40110000" in msg
    assert "auth headers" in msg


def test_holdings_empty_returns_zero_count(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v2/positions":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    auth = _paper_auth()
    client = httpx.Client(base_url=auth.base_url, headers=dict(auth.headers),
                           transport=httpx.MockTransport(handler))
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().get("/api/v2/holdings",
                                         query_string={"apikey": "x"})
    client.close()
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"holdings": [], "count": 0}
