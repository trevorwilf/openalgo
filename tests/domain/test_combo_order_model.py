"""Phase 8 — NormalizedComboOrderRequest + OrderLeg."""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import (
    ComboType,
    OrderSide,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedComboOrderRequest, OrderLeg


def _ref(symbol: str) -> InstrumentRef:
    return InstrumentRef(venue_code="XNAS", canonical_symbol=symbol)


def _market_leg(symbol: str = "AAPL") -> OrderLeg:
    return OrderLeg(
        instrument_ref=_ref(symbol),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        order_type=OrderType.MARKET,
    )


def _limit_leg(symbol: str = "AAPL", price: str = "100") -> OrderLeg:
    return OrderLeg(
        instrument_ref=_ref(symbol),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        order_type=OrderType.LIMIT,
        price=Decimal(price),
    )


def test_single_combo_with_one_leg() -> None:
    req = NormalizedComboOrderRequest(
        combo_type=ComboType.SINGLE,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_market_leg()],
    )
    assert len(req.legs) == 1


def test_single_combo_rejects_multiple_legs() -> None:
    with pytest.raises(Exception):
        NormalizedComboOrderRequest(
            combo_type=ComboType.SINGLE,
            time_in_force=TimeInForce.DAY,
            session=Session.REGULAR,
            legs=[_market_leg("AAPL"), _market_leg("MSFT")],
        )


def test_oto_requires_two_or_more_legs() -> None:
    with pytest.raises(Exception):
        NormalizedComboOrderRequest(
            combo_type=ComboType.OTO,
            time_in_force=TimeInForce.DAY,
            session=Session.REGULAR,
            legs=[_market_leg("AAPL")],
        )


def test_oco_two_legs() -> None:
    req = NormalizedComboOrderRequest(
        combo_type=ComboType.OCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_limit_leg("AAPL", "100"), _limit_leg("AAPL", "110")],
    )
    assert req.combo_type == ComboType.OCO
    assert len(req.legs) == 2


def test_otoco_three_legs() -> None:
    req = NormalizedComboOrderRequest(
        combo_type=ComboType.OTOCO,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_market_leg("AAPL"), _limit_leg("AAPL", "120"), _limit_leg("AAPL", "90")],
    )
    assert len(req.legs) == 3


def test_bracket_requires_three_legs() -> None:
    # 2 legs — should fail.
    with pytest.raises(Exception):
        NormalizedComboOrderRequest(
            combo_type=ComboType.BRACKET,
            time_in_force=TimeInForce.DAY,
            session=Session.REGULAR,
            legs=[_market_leg(), _limit_leg("AAPL", "120")],
        )
    # 3 legs — succeeds.
    req = NormalizedComboOrderRequest(
        combo_type=ComboType.BRACKET,
        time_in_force=TimeInForce.DAY,
        session=Session.REGULAR,
        legs=[_market_leg(), _limit_leg("AAPL", "120"), _limit_leg("AAPL", "90")],
    )
    assert len(req.legs) == 3


def test_empty_legs_rejected() -> None:
    with pytest.raises(Exception):
        NormalizedComboOrderRequest(
            combo_type=ComboType.OTO,
            time_in_force=TimeInForce.DAY,
            session=Session.REGULAR,
            legs=[],
        )


def test_order_leg_limit_requires_price() -> None:
    with pytest.raises(Exception):
        OrderLeg(
            instrument_ref=_ref("AAPL"),
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            quantity_unit=QuantityUnit.WHOLE,
            order_type=OrderType.LIMIT,
        )


def test_order_leg_quantity_must_be_positive() -> None:
    with pytest.raises(Exception):
        OrderLeg(
            instrument_ref=_ref("AAPL"),
            side=OrderSide.BUY,
            quantity=Decimal("0"),
            quantity_unit=QuantityUnit.WHOLE,
            order_type=OrderType.MARKET,
        )


def test_combo_order_extra_forbid() -> None:
    with pytest.raises(Exception):
        NormalizedComboOrderRequest(
            combo_type=ComboType.SINGLE,
            time_in_force=TimeInForce.DAY,
            session=Session.REGULAR,
            legs=[_market_leg()],
            unknown_field="x",  # type: ignore[call-arg]
        )
