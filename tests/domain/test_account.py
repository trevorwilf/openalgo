"""Normalized account shapes."""

from __future__ import annotations

from decimal import Decimal

from domain.currency import Currency, CurrencyAmount
from domain.enums import AssetClass, PositionEffect, QuantityUnit
from domain.instrument_ref import InstrumentRef
from domain.account import NormalizedBalance, NormalizedHolding, NormalizedPosition


def _ref() -> InstrumentRef:
    return InstrumentRef(venue_code="NSE", canonical_symbol="INFY")


def test_position_roundtrip() -> None:
    p = NormalizedPosition(
        instrument=_ref(),
        quantity=Decimal("100"),
        quantity_unit=QuantityUnit.WHOLE,
        average_price=Decimal("1500"),
        currency=Currency.INR,
        unrealized_pnl=CurrencyAmount(amount=Decimal("500"), currency=Currency.INR),
        realized_pnl=CurrencyAmount(amount=Decimal("0"), currency=Currency.INR),
        position_effect=PositionEffect.OPEN,
        asset_class=AssetClass.EQUITY,
        extra={"exchange": "NSE"},
    )
    assert p.quantity == Decimal("100")
    assert p.unrealized_pnl.amount == Decimal("500")
    assert p.asset_class is AssetClass.EQUITY
    assert p.extra["exchange"] == "NSE"


def test_balance_roundtrip() -> None:
    b = NormalizedBalance(
        available=CurrencyAmount(amount=Decimal("100000"), currency=Currency.INR),
        total=CurrencyAmount(amount=Decimal("125000"), currency=Currency.INR),
        used_margin=CurrencyAmount(amount=Decimal("25000"), currency=Currency.INR),
    )
    assert b.available.currency is Currency.INR
    assert b.used_margin is not None
    assert b.used_margin.amount == Decimal("25000")


def test_holding_roundtrip() -> None:
    h = NormalizedHolding(
        instrument=_ref(),
        quantity=Decimal("50"),
        quantity_unit=QuantityUnit.WHOLE,
        average_price=Decimal("1400"),
        currency=Currency.INR,
        current_price=Decimal("1550"),
        asset_class=AssetClass.EQUITY,
    )
    assert h.current_price == Decimal("1550")


def test_position_extra_defaults_to_empty_dict() -> None:
    p = NormalizedPosition(
        instrument=_ref(),
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        average_price=Decimal("100"),
        currency=Currency.INR,
    )
    assert p.extra == {}
