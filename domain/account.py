"""Normalized account shapes: position, balance, holding.

These mirror the semantic shape of current `/api/v1` account payloads
but with explicit typed fields and a passthrough `extra` dict for
broker-specific additions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.currency import Currency, CurrencyAmount
from domain.enums import AssetClass, PositionEffect, QuantityUnit
from domain.instrument_ref import InstrumentRef


class NormalizedPosition(BaseModel):
    """An open position, long or short."""

    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentRef
    quantity: Decimal
    quantity_unit: QuantityUnit
    average_price: Decimal
    currency: Currency
    unrealized_pnl: CurrencyAmount | None = None
    realized_pnl: CurrencyAmount | None = None
    position_effect: PositionEffect = PositionEffect.NONE
    asset_class: AssetClass | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedBalance(BaseModel):
    """A cash balance in a single currency."""

    model_config = ConfigDict(extra="forbid")

    available: CurrencyAmount
    total: CurrencyAmount
    used_margin: CurrencyAmount | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedHolding(BaseModel):
    """A long-term holding (equity delivery), distinct from intraday position."""

    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentRef
    quantity: Decimal
    quantity_unit: QuantityUnit
    average_price: Decimal
    currency: Currency
    current_price: Decimal | None = None
    asset_class: AssetClass | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedAccountSnapshot(BaseModel):
    """Combined account view: balance + open positions.

    Promoted from :class:`broker.alpaca.api.account_api.AccountSnapshot`
    in Phase 7. The compliance harness uses this as the canonical
    account-context contract every promoted broker plugin must produce.
    Schwab will populate ``account_hash`` for hash-addressed accounts.
    """

    model_config = ConfigDict(extra="forbid")

    account_id: str
    currency: Currency
    balance: NormalizedBalance
    positions: list[NormalizedPosition] = Field(default_factory=list)
    account_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "NormalizedAccountSnapshot",
    "NormalizedBalance",
    "NormalizedHolding",
    "NormalizedPosition",
]
