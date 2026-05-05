"""AlpacaOrderTranslator — validate, to_native, from_native_order_response."""

from __future__ import annotations

from collections import namedtuple
from decimal import Decimal

import httpx
import pytest

_EnumStub = namedtuple("_EnumStub", ["value"])  # hashable, exposes .value

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


def test_validate_accepts_stop_order():
    """Branch I — STOP is now a supported order type."""
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
    AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_validate_accepts_stop_limit_order():
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.STOP_LIMIT,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal("99.50"),
        trigger_price=Decimal("100.00"),
        time_in_force=TimeInForce.DAY,
    )
    AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_validate_accepts_trailing_stop_order():
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.SELL,
        order_type=OrderType.TRAILING_STOP,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        trigger_price=Decimal("100.00"),
        trailing_offset=Decimal("1.50"),
        time_in_force=TimeInForce.DAY,
    )
    AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_to_native_market_on_open_emits_market_with_opg_tif():
    """Branch J — MARKET_ON_OPEN collapses to type=market + tif=opg
    on the wire (Alpaca represents the auction via the TIF)."""
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET_ON_OPEN,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        time_in_force=TimeInForce.OPG,
    )
    body = AlpacaOrderTranslator().to_native(order, _Resolved(), _ctx())
    assert body["type"] == "market"
    assert body["time_in_force"] == "opg"


def test_to_native_limit_on_close_emits_limit_with_cls_tif():
    """Branch J — LIMIT_ON_CLOSE collapses to type=limit + tif=cls."""
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT_ON_CLOSE,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal("180.00"),
        time_in_force=TimeInForce.ATC,
    )
    body = AlpacaOrderTranslator().to_native(order, _Resolved(), _ctx())
    assert body["type"] == "limit"
    assert body["time_in_force"] == "cls"
    assert body["limit_price"] == "180.00"


def test_to_native_ioc_market_emits_ioc_tif():
    body = AlpacaOrderTranslator().to_native(
        _order(tif=TimeInForce.IOC), _Resolved(), _ctx()
    )
    assert body["time_in_force"] == "ioc"


def test_to_native_fok_market_emits_fok_tif():
    body = AlpacaOrderTranslator().to_native(
        _order(tif=TimeInForce.FOK), _Resolved(), _ctx()
    )
    assert body["time_in_force"] == "fok"


def test_validate_accepts_ioc():
    """Branch J — IOC is now a supported TIF."""
    AlpacaOrderTranslator().validate(
        _order(tif=TimeInForce.IOC), _Resolved(), _ctx()
    )


def test_validate_accepts_fok():
    AlpacaOrderTranslator().validate(
        _order(tif=TimeInForce.FOK), _Resolved(), _ctx()
    )


def test_validate_accepts_opg_with_market_on_open():
    """OPG TIF requires the corresponding *_ON_OPEN order type per
    the domain validator."""
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET_ON_OPEN,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        time_in_force=TimeInForce.OPG,
    )
    AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_validate_accepts_atc_with_limit_on_close():
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT_ON_CLOSE,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal("180.00"),
        time_in_force=TimeInForce.ATC,
    )
    AlpacaOrderTranslator().validate(order, _Resolved(), _ctx())


def test_validate_accepts_pre_market_limit_day_order():
    """Branch K — extended-hours sessions are supported with the
    Alpaca-required combination: type=LIMIT and TIF=DAY."""
    AlpacaOrderTranslator().validate(
        _order(
            order_type=OrderType.LIMIT,
            tif=TimeInForce.DAY,
            price="180.00",
            session=Session.PRE_MARKET,
        ),
        _Resolved(),
        _ctx(),
    )


def test_validate_accepts_post_market_limit_day_order():
    AlpacaOrderTranslator().validate(
        _order(
            order_type=OrderType.LIMIT,
            tif=TimeInForce.DAY,
            price="180.00",
            session=Session.POST_MARKET,
        ),
        _Resolved(),
        _ctx(),
    )


def test_validate_rejects_extended_hours_market_order():
    """Alpaca extended-hours orders must be LIMIT — MARKET is rejected
    fail-fast at the translator (saves a 422 round-trip to Alpaca)."""
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(
                order_type=OrderType.MARKET,
                tif=TimeInForce.DAY,
                session=Session.PRE_MARKET,
            ),
            _Resolved(),
            _ctx(),
        )


def test_validate_rejects_extended_hours_gtc_order():
    """Alpaca extended-hours orders must use TIF=DAY — GTC is rejected."""
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(
                order_type=OrderType.LIMIT,
                tif=TimeInForce.GTC,
                price="180.00",
                session=Session.POST_MARKET,
            ),
            _Resolved(),
            _ctx(),
        )


def test_validate_rejects_unsupported_session():
    """OPENING_AUCTION etc. remain unsupported — the four
    Alpaca-supported sessions are REGULAR / PRE_MARKET / POST_MARKET /
    EXTENDED."""
    with pytest.raises(UnsupportedCapability):
        AlpacaOrderTranslator().validate(
            _order(session=Session.OPENING_AUCTION),
            _Resolved(),
            _ctx(),
        )


def test_to_native_extended_hours_emits_flag():
    body = AlpacaOrderTranslator().to_native(
        _order(
            order_type=OrderType.LIMIT,
            tif=TimeInForce.DAY,
            price="180.00",
            session=Session.PRE_MARKET,
        ),
        _Resolved(),
        _ctx(),
    )
    assert body["extended_hours"] is True


def test_to_native_regular_session_omits_flag():
    body = AlpacaOrderTranslator().to_native(
        _order(order_type=OrderType.LIMIT, price="180.00"),
        _Resolved(),
        _ctx(),
    )
    assert "extended_hours" not in body


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


# ---- Branch I — STOP / STOP_LIMIT / TRAILING_STOP ----------------------


def _stop_order(order_type, *, price=None, trigger=None, trail=None):
    return NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.SELL,
        order_type=order_type,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal(price) if price is not None else None,
        trigger_price=Decimal(trigger) if trigger is not None else None,
        trailing_offset=Decimal(trail) if trail is not None else None,
        time_in_force=TimeInForce.DAY,
    )


def test_to_native_stop_emits_stop_price():
    body = AlpacaOrderTranslator().to_native(
        _stop_order(OrderType.STOP, trigger="180.00"),
        _Resolved(),
        _ctx(),
    )
    assert body["type"] == "stop"
    assert body["stop_price"] == "180.00"
    assert "limit_price" not in body
    assert "trail_price" not in body
    assert "trail_percent" not in body


def test_to_native_stop_limit_emits_both_prices():
    body = AlpacaOrderTranslator().to_native(
        _stop_order(OrderType.STOP_LIMIT, price="179.50", trigger="180.00"),
        _Resolved(),
        _ctx(),
    )
    assert body["type"] == "stop_limit"
    assert body["stop_price"] == "180.00"
    assert body["limit_price"] == "179.50"


def test_to_native_trailing_stop_default_to_trail_price():
    body = AlpacaOrderTranslator().to_native(
        _stop_order(OrderType.TRAILING_STOP, trigger="180.00", trail="1.50"),
        _Resolved(),
        _ctx(),
    )
    assert body["type"] == "trailing_stop"
    assert body["trail_price"] == "1.50"
    assert "trail_percent" not in body


def test_to_native_trailing_stop_percent_via_extra_hint():
    """Operators flip percent semantics via order.extra['alpaca_trail_unit']."""
    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
        side=OrderSide.SELL,
        order_type=OrderType.TRAILING_STOP,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        trigger_price=Decimal("180.00"),
        trailing_offset=Decimal("0.5"),
        time_in_force=TimeInForce.DAY,
        extra={"alpaca_trail_unit": "percent"},
    )
    body = AlpacaOrderTranslator().to_native(order, _Resolved(), _ctx())
    assert body["type"] == "trailing_stop"
    assert body["trail_percent"] == "0.5"
    assert "trail_price" not in body


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
    # v5 status normalization: native Alpaca strings are mapped to
    # the canonical FIX-aligned vocabulary (`NEW`/`FILLED`/etc.) and
    # the original native string is preserved under `native_status`.
    assert resp["status"] == "NEW"
    assert resp["native_status"] == "accepted"
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


class _BadOrder:
    """Minimal order-shaped object for exercising AlpacaOrderTranslator
    .validate() against bogus values. Bypasses NormalizedOrderRequest's
    type-checked construction so we can simulate the error path that
    fires when a future enum addition or a misuse slips an unsupported
    value in.
    """

    def __init__(self, *, order_type=OrderType.MARKET, tif=TimeInForce.DAY):
        self.order_type = order_type
        self.time_in_force = tif
        self.session = Session.REGULAR
        self.quantity_unit = QuantityUnit.WHOLE


def test_validate_unsupported_order_type_message_lists_actual_supported_set():
    """Regression: the ``UnsupportedCapability`` raised for a bad
    order_type used to advertise "MVP supports MARKET/LIMIT only"
    even after STOP / STOP_LIMIT / TRAILING_STOP and the four auction
    variants were added. Operators saw a misleading hint pointing to
    a smaller set than the translator actually accepts.

    The corrected message must enumerate the live set so an operator
    debugging a 422 has the actual list to choose from.
    """
    t = AlpacaOrderTranslator()
    bad = _BadOrder()
    # Enum-shaped stub so the validator's ``.value`` formatting works
    # the same way it would for a real (but unsupported) enum member.
    bad.order_type = _EnumStub(value="garbage_type_str")
    with pytest.raises(UnsupportedCapability) as exc:
        t.validate(bad, _Resolved(), {"broker_code": "alpaca"})
    # The new message must NOT contain the stale hint and MUST
    # mention at least one of the actually-supported types.
    msg = str(exc.value)
    assert "MARKET/LIMIT only" not in msg
    assert "TRAILING_STOP" in msg or "STOP_LIMIT" in msg


def test_validate_unsupported_tif_message_lists_actual_supported_set():
    """Regression: the TIF-rejection error used to advertise
    "DAY/GTC only" but the translator now accepts IOC / FOK / OPG /
    ATC as well. Surface the actual supported set.
    """
    t = AlpacaOrderTranslator()
    bad = _BadOrder()
    bad.time_in_force = _EnumStub(value="garbage_tif")
    with pytest.raises(UnsupportedCapability) as exc:
        t.validate(bad, _Resolved(), {"broker_code": "alpaca"})
    msg = str(exc.value)
    assert "DAY/GTC only" not in msg
    assert "IOC" in msg or "GTC" in msg
