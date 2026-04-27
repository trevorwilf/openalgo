"""v5 Phase 6 — `supports_screener_providers` capability propagation."""

from __future__ import annotations

from domain.capabilities import (
    BrokerCapabilities,
    Currency,
    MarketFamily,
    infer_capabilities_from_legacy,
)


def test_indian_inference_sets_supports_screener_providers_true():
    inferred = infer_capabilities_from_legacy(
        plugin_data={"broker_type": "IN_stock"},
        broker_code="zerodha",
    )
    assert inferred["supports_screener_providers"] is True


def test_crypto_inference_keeps_supports_screener_providers_false():
    inferred = infer_capabilities_from_legacy(
        plugin_data={
            "broker_type": "crypto",
            "supported_regions": ["india"],
        },
        broker_code="deltaexchange",
    )
    assert inferred["supports_screener_providers"] is False


def test_explicit_plugin_value_overrides_inference():
    caps = BrokerCapabilities(
        broker_code="_mock_x",
        broker_display_name="Mock X",
        market_families=[MarketFamily.US_STOCK],
        supported_regions=["us"],
        supported_venue_codes=["XNYS"],
        supported_asset_classes=[],
        supported_order_types=[],
        supported_time_in_force=[],
        supported_sessions=[],
        supported_quantity_units=[],
        trading_currencies=[Currency.USD],
        base_currency=Currency.USD,
        supports_screener_providers=True,
    )
    assert caps.supports_screener_providers is True


def test_default_unset_capability_is_false():
    caps = BrokerCapabilities(
        broker_code="_mock_y",
        broker_display_name="Mock Y",
        market_families=[MarketFamily.US_STOCK],
        supported_regions=["us"],
        supported_venue_codes=[],
        supported_asset_classes=[],
        supported_order_types=[],
        supported_time_in_force=[],
        supported_sessions=[],
        supported_quantity_units=[],
        trading_currencies=[Currency.USD],
        base_currency=Currency.USD,
    )
    assert caps.supports_screener_providers is False
