"""NormalizedOrderRequest cross-field validators."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.currency import Currency
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest


def _ref() -> InstrumentRef:
    return InstrumentRef(venue_code="NSE", canonical_symbol="RELIANCE")


def _base_kwargs(**overrides):
    data = {
        "instrument": _ref(),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1"),
        "quantity_unit": QuantityUnit.WHOLE,
        "time_in_force": TimeInForce.DAY,
    }
    data.update(overrides)
    return data


def test_valid_market_day() -> None:
    o = NormalizedOrderRequest(**_base_kwargs())
    assert o.session == Session.REGULAR
    assert o.position_effect == PositionEffect.NONE


def test_valid_limit_with_price() -> None:
    o = NormalizedOrderRequest(
        **_base_kwargs(order_type=OrderType.LIMIT, price=Decimal("100"))
    )
    assert o.order_type == OrderType.LIMIT


@pytest.mark.parametrize("ot", [OrderType.LIMIT, OrderType.STOP_LIMIT,
                                OrderType.LIMIT_ON_OPEN, OrderType.LIMIT_ON_CLOSE])
def test_limit_type_requires_price(ot: OrderType) -> None:
    kwargs = _base_kwargs(order_type=ot)
    if ot in (OrderType.STOP_LIMIT, OrderType.LIMIT_ON_CLOSE):
        # Still needs trigger_price / tif-or-type pairing downstream; provide a
        # config that fails specifically on missing price.
        if ot == OrderType.STOP_LIMIT:
            kwargs["trigger_price"] = Decimal("99")
        if ot == OrderType.LIMIT_ON_CLOSE:
            kwargs["time_in_force"] = TimeInForce.ATC
        if ot == OrderType.LIMIT_ON_OPEN:
            kwargs["time_in_force"] = TimeInForce.OPG
    with pytest.raises(ValidationError, match="requires price"):
        NormalizedOrderRequest(**kwargs)


@pytest.mark.parametrize("ot", [OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP])
def test_stop_type_requires_trigger_price(ot: OrderType) -> None:
    kwargs = _base_kwargs(order_type=ot)
    if ot == OrderType.STOP_LIMIT:
        kwargs["price"] = Decimal("100")
    if ot == OrderType.TRAILING_STOP:
        kwargs["trailing_offset"] = Decimal("1")
    with pytest.raises(ValidationError, match="requires trigger_price"):
        NormalizedOrderRequest(**kwargs)


def test_trailing_stop_requires_offset() -> None:
    with pytest.raises(ValidationError, match="trailing_offset"):
        NormalizedOrderRequest(
            **_base_kwargs(
                order_type=OrderType.TRAILING_STOP,
                trigger_price=Decimal("95"),
            )
        )


def test_gtd_requires_good_till() -> None:
    with pytest.raises(ValidationError, match="GTD requires good_till"):
        NormalizedOrderRequest(**_base_kwargs(time_in_force=TimeInForce.GTD))


def test_good_till_without_gtd_rejected() -> None:
    with pytest.raises(ValidationError, match="good_till only valid"):
        NormalizedOrderRequest(
            **_base_kwargs(
                time_in_force=TimeInForce.DAY,
                good_till=datetime.now(tz=timezone.utc) + timedelta(days=1),
            )
        )


def test_gtd_with_good_till_valid() -> None:
    o = NormalizedOrderRequest(
        **_base_kwargs(
            time_in_force=TimeInForce.GTD,
            good_till=datetime.now(tz=timezone.utc) + timedelta(days=1),
        )
    )
    assert o.time_in_force == TimeInForce.GTD


def test_opg_requires_mo_or_lo_open() -> None:
    with pytest.raises(ValidationError, match="OPG requires"):
        NormalizedOrderRequest(
            **_base_kwargs(time_in_force=TimeInForce.OPG, order_type=OrderType.MARKET)
        )


def test_opg_with_moo_valid() -> None:
    o = NormalizedOrderRequest(
        **_base_kwargs(time_in_force=TimeInForce.OPG, order_type=OrderType.MARKET_ON_OPEN)
    )
    assert o.time_in_force == TimeInForce.OPG


def test_atc_requires_mo_or_lo_close() -> None:
    with pytest.raises(ValidationError, match="ATC requires"):
        NormalizedOrderRequest(
            **_base_kwargs(time_in_force=TimeInForce.ATC, order_type=OrderType.MARKET)
        )


def test_atc_with_moc_valid() -> None:
    o = NormalizedOrderRequest(
        **_base_kwargs(time_in_force=TimeInForce.ATC, order_type=OrderType.MARKET_ON_CLOSE)
    )
    assert o.order_type == OrderType.MARKET_ON_CLOSE


def test_zero_quantity_rejected() -> None:
    with pytest.raises(ValidationError, match="quantity must be positive"):
        NormalizedOrderRequest(**_base_kwargs(quantity=Decimal("0")))


def test_negative_quantity_rejected() -> None:
    with pytest.raises(ValidationError, match="quantity must be positive"):
        NormalizedOrderRequest(**_base_kwargs(quantity=Decimal("-1")))


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizedOrderRequest(**_base_kwargs(), bogus_field="x")


def test_currency_and_tags_roundtrip() -> None:
    o = NormalizedOrderRequest(
        **_base_kwargs(
            currency=Currency.USDT,
            client_order_id="co-1",
            strategy_tag="scalper-v1",
            extra={"broker_hint": "post_only"},
        )
    )
    assert o.currency is Currency.USDT
    assert o.client_order_id == "co-1"
    assert o.strategy_tag == "scalper-v1"
    assert o.extra["broker_hint"] == "post_only"
