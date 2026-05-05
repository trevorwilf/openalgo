"""Phase 6c — /api/v2/orders with Alpaca translator, mocked HTTP."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from broker.alpaca.sync.seed_rules import seed_alpaca_rules
from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)
from services.broker_translator_registry import (
    clear_registry_for_tests,
    register_broker_translator,
)


NEW_ORDER_RESP = {
    "id": "alpaca-order-1",
    "client_order_id": "coid-1",
    "status": "new",
    "symbol": "AAPL",
    "qty": "1",
    "filled_qty": "0",
    "filled_avg_price": None,
}


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


def _orders_client() -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/orders" and req.method == "POST":
            return httpx.Response(200, json=NEW_ORDER_RESP)
        return httpx.Response(404, json={"message": "not found"})

    auth = _paper_auth()
    return httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


def _install_fake_auth_resolver(monkeypatch):
    def fake_resolve_auth():
        return "fake-token", "alpaca", None

    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", fake_resolve_auth)


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


def test_place_market_aapl_via_promoted_alpaca(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)
    _seed_aapl()
    seed_alpaca_rules()

    auth = _paper_auth()
    client = _orders_client()
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    # Legacy paths must never be loaded.
    def _raise(*a, **kw):
        raise AssertionError("legacy path hit on promoted request")

    monkeypatch.setattr(
        "domain.translators.normalized_order_to_legacy_fields", _raise
    )
    monkeypatch.setattr(
        "services.place_order_service.place_order_with_auth", _raise
    )

    body = {
        "apikey": "x",
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
    }
    resp = flask_app.test_client().post("/api/v2/orders", json=body)
    client.close()
    assert resp.status_code == 200, resp.get_json()
    j = resp.get_json()
    assert j["data"]["order_id"] == "alpaca-order-1"
    # ``status`` is canonical (domain.enums.OrderStatus.NEW.value =
    # "NEW") — the native Alpaca status "new" is preserved at
    # ``native_status``.
    assert j["data"]["status"] == "NEW"
    assert j["data"]["native_status"] == "new"
