"""AlpacaOrderTranslator — validate, to_native, from_native_order_response."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest


class _Resolved:
    def __init__(self, symbol="AAPL", venue="XNAS", broker_native=None):
        self.instrument_id = "00000000-0000-0000-0000-000000000001"
        self.venue_code = venue
        self.canonical_symbol = symbol
        self.broker_native_symbol = broker_native or symbol
        self.broker_native_token = "alpaca-id"
        self.supports_fractional = True
        self.currency = "USD"


def _order(
    order_type=OrderType.MARKET,
    tif=TimeInForce.DAY,
    qu=QuantityUnit.WHOLE,
    qty="1",
    price=None,
    session=Session.REGULAR,
):
    return NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Decimal(qty),
        quantity_unit=qu,
        time_in_force=tif,
        session=session,
        price=Decimal(price) if price is not None else None,
    )


def _ctx():
    return {"broker_code": "alpaca", "account_id": "fake"}


def test_validate_market_day_ok():
    AlpacaOrderTranslator().validate(_order(), _Resolved(), _ctx())


def test_validate_rejects_stop_order():
    from domain.enums import OrderType as OT

    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OT.STOP,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        trigger_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
    )
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_validate_rejects_ioc():
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(tif=TimeInForce.IOC), _Resolved(), _ctx()
        )


def test_validate_rejects_non_regular_session():
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(session=Session.PRE_MARKET),
            _Resolved(),
            _ctx(),
        )


def test_validate_rejects_unknown_venue():
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(),
            _Resolved(venue="NSE"),
            _ctx(),
        )


def test_to_native_market_whole_qty():
    body = AlpacaOrderTranslator().to_native(_order(), _Resolved(), _ctx())
    assert body == {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "qty": "1",
    }


def test_to_native_market_fractional_qty():
    body = AlpacaOrderTranslator().to_native(
        _order(qu=QuantityUnit.FRACTIONAL, qty="0.5"),
        _Resolved(),
        _ctx(),
    )
    assert body["qty"] == "0.5"


def test_to_native_market_notional_qty():
    body = AlpacaOrderTranslator().to_native(
        _order(qu=QuantityUnit.NOTIONAL, qty="100"),
        _Resolved(),
        _ctx(),
    )
    assert body["notional"] == "100"
    assert "qty" not in body


def test_to_native_limit_with_price_and_gtc():
    body = AlpacaOrderTranslator().to_native(
        _order(order_type=OrderType.LIMIT, tif=TimeInForce.GTC, price="175.50"),
        _Resolved(),
        _ctx(),
    )
    assert body["type"] == "limit"
    assert body["limit_price"] == "175.50"
    assert body["time_in_force"] == "gtc"


def test_from_native_order_response_happy():
    translator = AlpacaOrderTranslator()
    resp = translator.from_native_order_response(
        {
            "id": "abcd-efgh",
            "status": "accepted",
            "filled_qty": "0",
            "filled_avg_price": None,
            "symbol": "AAPL",
        },
        _Resolved(),
    )
    assert resp["order_id"] == "abcd-efgh"
    assert resp["status"] == "accepted"
    assert resp["filled_quantity"] == "0"


def test_from_native_missing_id_raises():
    with pytest.raises(ValueError):
        AlpacaOrderTranslator().from_native_order_response({}, _Resolved())


def _translator_with_mock(handler) -> AlpacaOrderTranslator:
    auth = AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )
    client = httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )
    return AlpacaOrderTranslator(auth=auth, client=client)


def test_send_native_posts_to_v2_orders():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/orders" and req.method == "POST":
            captured["body"] = req.content
            return httpx.Response(
                200,
                json={
                    "id": "order-1",
                    "status": "new",
                    "filled_qty": "0",
                    "symbol": "AAPL",
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    t = _translator_with_mock(handler)
    try:
        resp = t.send_native(
            {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market",
             "time_in_force": "day"},
            {"broker_code": "alpaca"},
        )
    finally:
        t._client.close()
    assert resp["id"] == "order-1"
    assert captured["body"] is not None


def test_cancel_order_delete():
    called = {"delete": False}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/orders/abcd" and req.method == "DELETE":
            called["delete"] = True
            return httpx.Response(204)
        return httpx.Response(404)

    t = _translator_with_mock(handler)
    try:
        t.cancel_order("abcd")
    finally:
        t._client.close()
    assert called["delete"] is True
