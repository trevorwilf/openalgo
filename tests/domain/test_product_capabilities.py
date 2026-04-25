"""Phase 8 — ProductCapabilities + BrokerCapabilities Phase 8 fields."""

from __future__ import annotations

import pytest

from domain.capabilities import BrokerCapabilities, ProductCapabilities
from domain.currency import Currency
from domain.enums import (
    AssetClass,
    AuthMode,
    ComboType,
    MarketFamily,
    OrderType,
    QuantityUnit,
    Session,
    StreamTransport,
    TimeInForce,
)


def _base_caps(**overrides):
    payload = {
        "broker_code": "demo",
        "broker_display_name": "Demo",
        "market_families": [MarketFamily.US_STOCK],
        "supported_regions": ["us"],
        "supported_venue_codes": ["XNAS"],
        "supported_asset_classes": [AssetClass.EQUITY],
        "supported_order_types": [OrderType.MARKET, OrderType.LIMIT],
        "supported_time_in_force": [TimeInForce.DAY],
        "supported_sessions": [Session.REGULAR],
        "supported_quantity_units": [QuantityUnit.WHOLE],
        "trading_currencies": [Currency.USD],
        "base_currency": Currency.USD,
    }
    payload.update(overrides)
    return BrokerCapabilities(**payload)


def test_capabilities_default_phase8_fields_empty() -> None:
    caps = _base_caps()
    assert caps.products == []
    assert caps.auth_modes == []
    assert caps.streaming_transports == []
    assert caps.supports_account_hashes is False
    assert caps.supports_subaccounts is False


def test_per_product_capabilities_round_trip() -> None:
    eq = ProductCapabilities(
        asset_class=AssetClass.EQUITY,
        supported_order_types=[OrderType.MARKET, OrderType.LIMIT],
        supported_time_in_force=[TimeInForce.DAY],
        supported_sessions=[Session.REGULAR, Session.PRE_MARKET],
        supported_quantity_units=[QuantityUnit.WHOLE, QuantityUnit.FRACTIONAL],
        supports_fractional=True,
        supports_combo_types=[ComboType.SINGLE, ComboType.OCO, ComboType.OTOCO],
    )
    opt = ProductCapabilities(
        asset_class=AssetClass.OPTION,
        supported_order_types=[OrderType.MARKET, OrderType.LIMIT],
        supports_combo_types=[ComboType.SINGLE, ComboType.MULTILEG_OPTIONS],
    )
    caps = _base_caps(products=[eq, opt])
    assert len(caps.products) == 2
    assert caps.products[1].asset_class == AssetClass.OPTION


def test_auth_modes_streaming_transports_account_hashes() -> None:
    caps = _base_caps(
        auth_modes=[AuthMode.OAUTH, AuthMode.SIGNATURE],
        streaming_transports=[StreamTransport.WEBSOCKET, StreamTransport.MQTT],
        supports_account_hashes=True,
        supports_subaccounts=True,
    )
    assert AuthMode.OAUTH in caps.auth_modes
    assert StreamTransport.MQTT in caps.streaming_transports
    assert caps.supports_account_hashes
    assert caps.supports_subaccounts


def test_phase_8_fields_extra_forbid() -> None:
    with pytest.raises(Exception):
        _base_caps(products="not-a-list")


def test_product_capabilities_extra_forbid() -> None:
    with pytest.raises(Exception):
        ProductCapabilities(
            asset_class=AssetClass.EQUITY,
            unknown_field=True,  # type: ignore[call-arg]
        )
