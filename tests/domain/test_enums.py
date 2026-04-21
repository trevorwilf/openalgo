"""Exhaustive coverage of every enum value."""

from __future__ import annotations

from enum import StrEnum

import pytest

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

ALL_ENUMS = [
    MarketFamily,
    AssetClass,
    InstrumentKind,
    OrderSide,
    OrderType,
    TimeInForce,
    Session,
    QuantityUnit,
    SettlementType,
    PositionEffect,
    OptionRight,
    IdentifierType,
]


@pytest.mark.parametrize("enum_cls", ALL_ENUMS)
def test_is_str_enum(enum_cls: type[StrEnum]) -> None:
    assert issubclass(enum_cls, StrEnum)
    for member in enum_cls:
        assert isinstance(member, str)
        assert member.value == str(member)


def test_market_family_values() -> None:
    assert {m.value for m in MarketFamily} == {
        "IN_STOCK",
        "US_STOCK",
        "EU_STOCK",
        "UK_STOCK",
        "CRYPTO",
        "FUTURES",
        "FX",
        "COMMODITY",
        "OTHER",
    }


def test_asset_class_values() -> None:
    assert {m.value for m in AssetClass} == {
        "EQUITY",
        "ETF",
        "FUTURE",
        "OPTION",
        "PERPETUAL",
        "SPOT",
        "INDEX",
        "BOND",
        "WARRANT",
        "STRUCTURED",
        "OTHER",
    }


def test_instrument_kind_values() -> None:
    assert {m.value for m in InstrumentKind} == {"CASH", "DERIVATIVE", "SYNTHETIC", "NOTIONAL"}


def test_order_side_values() -> None:
    assert {m.value for m in OrderSide} == {"BUY", "SELL"}


def test_order_type_values() -> None:
    assert {m.value for m in OrderType} == {
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "TRAILING_STOP",
        "MARKET_ON_OPEN",
        "MARKET_ON_CLOSE",
        "LIMIT_ON_OPEN",
        "LIMIT_ON_CLOSE",
        "PEGGED",
    }


def test_time_in_force_values() -> None:
    assert {m.value for m in TimeInForce} == {
        "DAY",
        "GTC",
        "GTD",
        "IOC",
        "FOK",
        "OPG",
        "ATC",
    }


def test_session_values() -> None:
    assert {m.value for m in Session} == {
        "PRE_MARKET",
        "OPENING_AUCTION",
        "REGULAR",
        "INTRADAY_AUCTION",
        "CLOSING_AUCTION",
        "POST_MARKET",
        "EXTENDED",
        "ALL_DAY",
    }


def test_quantity_unit_values() -> None:
    assert {m.value for m in QuantityUnit} == {
        "WHOLE",
        "FRACTIONAL",
        "NOTIONAL",
        "CONTRACTS",
        "LOTS",
    }


def test_settlement_type_values() -> None:
    assert {m.value for m in SettlementType} == {
        "T0",
        "T1",
        "T2",
        "T_PLUS_N",
        "IMMEDIATE",
        "ROLLING",
    }


def test_position_effect_values() -> None:
    assert {m.value for m in PositionEffect} == {"OPEN", "CLOSE", "REDUCE_ONLY", "NONE"}


def test_option_right_values() -> None:
    assert {m.value for m in OptionRight} == {"CALL", "PUT"}


def test_identifier_type_values() -> None:
    assert {m.value for m in IdentifierType} == {
        "ISIN",
        "CUSIP",
        "SEDOL",
        "FIGI",
        "RIC",
        "VENUE_SYMBOL",
        "BROKER_TOKEN",
        "BROKER_SYMBOL",
        "CANONICAL_SYMBOL",
        "INTERNAL_ID",
    }


@pytest.mark.parametrize("enum_cls", ALL_ENUMS)
def test_roundtrip_via_value(enum_cls: type[StrEnum]) -> None:
    """Every member should be reconstructible from its .value."""
    for member in enum_cls:
        assert enum_cls(member.value) is member
