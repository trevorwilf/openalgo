"""Mock Schwab-LIKE account API — deterministic snapshot."""

from __future__ import annotations

from decimal import Decimal

from domain.account import (
    NormalizedAccountSnapshot,
    NormalizedBalance,
    NormalizedPosition,
)
from domain.account_context import AccountContext
from domain.currency import Currency, CurrencyAmount
from domain.enums import AssetClass, PositionEffect, QuantityUnit
from domain.instrument_ref import InstrumentRef


def get_account(account_ctx: AccountContext) -> NormalizedAccountSnapshot:
    cash = CurrencyAmount(amount=Decimal("10000.00"), currency=Currency.USD)
    return NormalizedAccountSnapshot(
        account_id=account_ctx.account_id,
        account_hash=account_ctx.account_hash,
        currency=Currency.USD,
        balance=NormalizedBalance(available=cash, total=cash),
        positions=get_positions(account_ctx),
        metadata={"source": "mock_schwab_like"},
    )


def get_positions(account_ctx: AccountContext) -> list[NormalizedPosition]:
    return [
        NormalizedPosition(
            instrument=InstrumentRef(venue_code="XNAS", canonical_symbol="AAPL"),
            quantity=Decimal("10"),
            quantity_unit=QuantityUnit.WHOLE,
            average_price=Decimal("150.00"),
            currency=Currency.USD,
            asset_class=AssetClass.EQUITY,
            position_effect=PositionEffect.OPEN,
        ),
    ]


__all__ = ["get_account", "get_positions"]
