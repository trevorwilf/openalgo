"""Market-agnostic domain types for the OpenAlgo core.

This package is the internal vocabulary for orders, instruments,
market data, accounts, and capabilities. It imports nothing from
`utils.constants`, `database.*`, or `broker.*` — those are legacy
Indian-shaped layers. See docs/adr/0002-no-specific-target-broker.md
for the rationale.

Public surface re-exported here for ergonomic imports:

    from domain import (
        AssetClass, MarketFamily, OrderSide, OrderType,
        TimeInForce, Session, QuantityUnit, InstrumentKind,
        SettlementType, PositionEffect, OptionRight, IdentifierType,
        Currency, CurrencyAmount,
        InstrumentRef,
        NormalizedOrderRequest,
        NormalizedQuote, NormalizedBar, NormalizedDepth, NormalizedDepthLevel,
        NormalizedPosition, NormalizedBalance, NormalizedHolding,
        DomainError, InstrumentNotResolvable, UnsupportedCapability,
        CapabilityMismatch, ValidationError,
    )
"""

from domain.account import NormalizedBalance, NormalizedHolding, NormalizedPosition
from domain.currency import Currency, CurrencyAmount
from domain.enums import (
    AssetClass,
    IdentifierType,
    InstrumentKind,
    MarketFamily,
    OptionRight,
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    SettlementType,
    TimeInForce,
)
from domain.errors import (
    CapabilityMismatch,
    DomainError,
    InstrumentNotResolvable,
    UnsupportedCapability,
    ValidationError,
)
from domain.instrument_ref import InstrumentRef
from domain.market_data import (
    NormalizedBar,
    NormalizedDepth,
    NormalizedDepthLevel,
    NormalizedQuote,
)
from domain.orders import NormalizedOrderRequest

__all__ = [
    # enums
    "AssetClass",
    "IdentifierType",
    "InstrumentKind",
    "MarketFamily",
    "OptionRight",
    "OrderSide",
    "OrderType",
    "PositionEffect",
    "QuantityUnit",
    "Session",
    "SettlementType",
    "TimeInForce",
    # currency
    "Currency",
    "CurrencyAmount",
    # instrument ref
    "InstrumentRef",
    # orders
    "NormalizedOrderRequest",
    # market data
    "NormalizedBar",
    "NormalizedDepth",
    "NormalizedDepthLevel",
    "NormalizedQuote",
    # account
    "NormalizedBalance",
    "NormalizedHolding",
    "NormalizedPosition",
    # errors
    "CapabilityMismatch",
    "DomainError",
    "InstrumentNotResolvable",
    "UnsupportedCapability",
    "ValidationError",
]
