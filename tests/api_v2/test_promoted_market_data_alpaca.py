"""Phase 6b integration — /api/v2/quotes + /api/v2/bars with the Alpaca
adapters registered under API_V2_ALPACA=1.

All HTTP calls are intercepted via httpx MockTransport on the injected
client — no real network traffic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.bar_api import AlpacaBarAdapter
from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
from database import broker_rules_repo, instruments_repo
from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)
from services.broker_market_data_registry import (
    clear_market_data_registries_for_tests,
    register_broker_bar_adapter,
    register_broker_quote_adapter,
)


QUOTE_PAYLOAD = {
    "symbol": "AAPL",
    "quote": {
        "t": "2026-04-23T14:30:00.123Z",
        "ap": 175.02, "as": 200,
        "bp": 175.00, "bs": 100,
        "x": "XNAS",
    },
}

BARS_PAYLOAD = {
    "bars": {
        "AAPL": [
            {"t": "2026-04-23T14:30:00Z", "o": 175.0, "h": 175.5,
             "l": 174.9, "c": 175.3, "v": 12345},
        ]
    }
}


@pytest.fixture(autouse=True)
def _clean():
    clear_market_data_registries_for_tests()
    yield
    clear_market_data_registries_for_tests()


def _paper_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _data_client() -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/v2/stocks/AAPL/quotes/latest":
            return httpx.Response(200, json=QUOTE_PAYLOAD)
        if path == "/v2/stocks/bars":
            return httpx.Response(200, json=BARS_PAYLOAD)
        return httpx.Response(404, json={"message": "not found"})

    auth = _paper_auth()
    return httpx.Client(
        base_url=auth.data_base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


def _install_fake_auth_resolver(monkeypatch, broker_code: str = "alpaca"):
    def fake_resolve_auth():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.quotes.resolve_auth", fake_resolve_auth)
    monkeypatch.setattr("restx_api.v2.bars.resolve_auth", fake_resolve_auth)


def _seed_aapl():
    venues_upsert(
        "XNAS",
        market_family="US_STOCK",
        country_code="US",
        base_currency="USD",
        timezone_name="America/New_York",
    )
    aapl = instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="CASH",
        tick_size=Decimal("0.01"),
        quantity_precision=9,
        currency="USD",
    )
    broker_map_upsert_many(
        broker_code="alpaca",
        venue_code="XNAS",
        sync_version=1,
        rows=[
            BrokerMapRow(
                external_symbol="AAPL",
                external_token="alpaca-aapl-id",
                instrument_id=aapl.instrument_id,
            )
        ],
    )


def _forbid_legacy(monkeypatch):
    def _raise(*a, **kw):
        raise AssertionError("legacy symbol touched on promoted path")

    monkeypatch.setattr("services.quotes_service.get_quotes_with_auth", _raise)
    monkeypatch.setattr("services.history_service.get_history_with_auth", _raise)
    monkeypatch.setattr("database.token_db.get_token", _raise)


def test_promoted_alpaca_quote_roundtrip(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="alpaca")
    _forbid_legacy(monkeypatch)
    _seed_aapl()

    auth = _paper_auth()
    client = _data_client()
    register_broker_quote_adapter(AlpacaQuoteAdapter(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/quotes",
        json={
            "apikey": "x",
            "instruments": [
                {"venue_code": "XNAS", "canonical_symbol": "AAPL"}
            ],
        },
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()
    assert j["data"][0]["quote"]["ask"] == "175.02"


def test_promoted_alpaca_bar_roundtrip(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch, broker_code="alpaca")
    _forbid_legacy(monkeypatch)
    _seed_aapl()

    auth = _paper_auth()
    client = _data_client()
    register_broker_bar_adapter(AlpacaBarAdapter(auth=auth, client=client))

    resp = flask_app.test_client().post(
        "/api/v2/bars",
        json={
            "apikey": "x",
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "interval": "1m",
            "start": "2026-04-23T14:30:00+00:00",
            "end": "2026-04-23T15:00:00+00:00",
        },
    )
    client.close()
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()
    assert len(j["data"]["bars"]) == 1
    assert j["data"]["bars"][0]["close"] == "175.3"
