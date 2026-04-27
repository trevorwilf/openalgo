"""v5 Phase 4 — `supports_sandbox` capability propagation.

Verifies the new capability field round-trips through the loader,
the typed model, and stays consistent with India default = True /
non-India default = False.
"""

from __future__ import annotations

from domain.capabilities import (
    BrokerCapabilities,
    Currency,
    MarketFamily,
    infer_capabilities_from_legacy,
)


def test_indian_inference_sets_supports_sandbox_true():
    inferred = infer_capabilities_from_legacy(
        plugin_data={"broker_type": "IN_stock"},
        broker_code="zerodha",
    )
    assert inferred["supports_sandbox"] is True
    assert inferred["supports_analyzer"] is True


def test_crypto_inference_keeps_supports_sandbox_false():
    inferred = infer_capabilities_from_legacy(
        plugin_data={
            "broker_type": "crypto",
            "supported_regions": ["india"],  # legacy crypto plugins are still India-tagged
        },
        broker_code="deltaexchange",
    )
    assert inferred["supports_sandbox"] is False


def test_explicit_plugin_value_overrides_inference():
    """A non-India broker plugin can opt in by declaring the field."""
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
        supports_sandbox=True,
    )
    assert caps.supports_sandbox is True


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
    assert caps.supports_sandbox is False


def test_supports_sandbox_serialised_in_model_dump():
    caps = BrokerCapabilities(
        broker_code="zerodha",
        broker_display_name="Zerodha",
        market_families=[MarketFamily.IN_STOCK],
        supported_regions=["india"],
        supported_venue_codes=["NSE", "BSE"],
        supported_asset_classes=[],
        supported_order_types=[],
        supported_time_in_force=[],
        supported_sessions=[],
        supported_quantity_units=[],
        trading_currencies=[Currency.INR],
        base_currency=Currency.INR,
        supports_sandbox=True,
    )
    dumped = caps.model_dump()
    assert "supports_sandbox" in dumped
    assert dumped["supports_sandbox"] is True
