"""BrokerCapabilities model + legacy inference."""

from __future__ import annotations

import pytest

from domain.capabilities import (
    BrokerCapabilities,
    infer_capabilities_from_legacy,
    infer_supported_regions_from_market_families,
)
from domain.currency import Currency
from domain.enums import (
    AssetClass,
    MarketFamily,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)


def _minimal_capabilities(**overrides) -> BrokerCapabilities:
    data = {
        "broker_code": "demo",
        "broker_display_name": "Demo Broker",
        "market_families": [MarketFamily.IN_STOCK],
        "supported_venue_codes": ["NSE", "BSE"],
        "supported_asset_classes": [AssetClass.EQUITY],
        "supported_order_types": [OrderType.MARKET, OrderType.LIMIT],
        "supported_time_in_force": [TimeInForce.DAY],
        "supported_sessions": [Session.REGULAR],
        "supported_quantity_units": [QuantityUnit.WHOLE],
        "trading_currencies": [Currency.INR],
        "base_currency": Currency.INR,
    }
    data.update(overrides)
    return BrokerCapabilities(**data)


def test_required_fields_present() -> None:
    caps = _minimal_capabilities()
    assert caps.broker_code == "demo"
    assert caps.market_families == [MarketFamily.IN_STOCK]


def test_extra_field_rejected() -> None:
    with pytest.raises(Exception):
        _minimal_capabilities(unknown_flag=True)


def test_frozen() -> None:
    caps = _minimal_capabilities()
    with pytest.raises(Exception):
        caps.broker_code = "other"  # type: ignore[misc]


def test_broker_type_alias_indian() -> None:
    assert _minimal_capabilities().broker_type == "IN_stock"


def test_broker_type_alias_crypto_only() -> None:
    caps = _minimal_capabilities(market_families=[MarketFamily.CRYPTO])
    assert caps.broker_type == "crypto"


def test_broker_type_alias_mixed_indian_wins() -> None:
    """IN_STOCK present anywhere in the list wins the legacy label."""
    caps = _minimal_capabilities(
        market_families=[MarketFamily.CRYPTO, MarketFamily.IN_STOCK]
    )
    assert caps.broker_type == "IN_stock"


def test_broker_type_alias_first_family_lowered() -> None:
    caps = _minimal_capabilities(market_families=[MarketFamily.US_STOCK])
    assert caps.broker_type == "us_stock"


def test_broker_type_alias_empty_families_is_unknown() -> None:
    caps = _minimal_capabilities(market_families=[])
    assert caps.broker_type == "unknown"


def test_broker_name_alias() -> None:
    caps = _minimal_capabilities(broker_code="abc")
    assert caps.broker_name == "abc"


def test_supported_exchanges_alias_copy() -> None:
    caps = _minimal_capabilities(supported_venue_codes=["NSE", "BSE", "NFO"])
    assert caps.supported_exchanges == ["NSE", "BSE", "NFO"]


def test_model_dump_includes_legacy_keys() -> None:
    caps = _minimal_capabilities()
    d = caps.model_dump(mode="json")
    assert d["broker_name"] == "demo"
    assert d["broker_type"] == "IN_stock"
    assert d["supported_exchanges"] == ["NSE", "BSE"]
    assert d["leverage_config"] is False
    # Rich fields also present
    assert d["market_families"] == ["IN_STOCK"]
    assert d["supports_analyzer"] is False


def test_has_capability_first_class_wins() -> None:
    caps = _minimal_capabilities(
        supports_fractional=True,
        features={"supports_fractional": False},
    )
    assert caps.has_capability("supports_fractional") is True


def test_has_capability_falls_through_to_features() -> None:
    caps = _minimal_capabilities(features={"custom_flag": True})
    assert caps.has_capability("custom_flag") is True


def test_has_capability_missing() -> None:
    caps = _minimal_capabilities()
    assert caps.has_capability("not_a_real_flag") is False


# ---- infer_capabilities_from_legacy ---------------------------------


def test_infer_indian_defaults() -> None:
    d = infer_capabilities_from_legacy(
        {
            "Plugin Name": "zerodha",
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["NSE", "NFO"],
            "broker_type": "IN_stock",
            "leverage_config": False,
        },
        broker_code="zerodha",
    )
    caps = BrokerCapabilities(**d)
    assert caps.market_families == [MarketFamily.IN_STOCK]
    assert caps.base_currency is Currency.INR
    assert caps.supports_analyzer is True
    assert caps.supports_fractional is False
    assert caps.supported_order_types == [
        OrderType.MARKET,
        OrderType.LIMIT,
        OrderType.STOP,
        OrderType.STOP_LIMIT,
    ]
    assert caps.supported_venue_codes == ["NSE", "NFO"]


def test_infer_crypto_defaults() -> None:
    d = infer_capabilities_from_legacy(
        {
            "Plugin Name": "deltaexchange",
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["CRYPTO"],
            "broker_type": "crypto",
            "leverage_config": True,
        },
        broker_code="deltaexchange",
    )
    caps = BrokerCapabilities(**d)
    assert caps.market_families == [MarketFamily.CRYPTO]
    assert caps.base_currency is Currency.USDT
    assert caps.supports_fractional is True
    assert caps.supports_analyzer is False
    assert caps.leverage_config is True
    assert TimeInForce.GTC in caps.supported_time_in_force
    assert Session.ALL_DAY in caps.supported_sessions


def test_infer_unknown_broker_type_uses_skeleton() -> None:
    d = infer_capabilities_from_legacy(
        {
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["XFOO"],
            "broker_type": "mystery_family",
        },
        broker_code="mystery",
    )
    caps = BrokerCapabilities(**d)
    assert caps.market_families == [MarketFamily.OTHER]
    assert caps.supports_analyzer is False
    assert caps.base_currency is None


def test_infer_explicit_fields_override_defaults() -> None:
    """Richer shapes declared in plugin.json win over the inferred defaults."""
    d = infer_capabilities_from_legacy(
        {
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["NSE"],
            "broker_type": "IN_stock",
            "leverage_config": False,
            # Override every overridable field with an unusual value
            "market_families": ["CRYPTO"],
            "supported_asset_classes": ["OPTION"],
            "supported_order_types": ["MARKET_ON_CLOSE"],
            "supported_time_in_force": ["FOK"],
            "supported_sessions": ["POST_MARKET"],
            "supported_quantity_units": ["NOTIONAL"],
            "trading_currencies": ["USD"],
            "base_currency": "USD",
            "supports_fractional": True,
            "supports_analyzer": False,
            "features": {"vip_only": True},
        },
        broker_code="hybrid",
    )
    caps = BrokerCapabilities(**d)
    assert caps.market_families == [MarketFamily.CRYPTO]
    assert caps.supported_order_types == [OrderType.MARKET_ON_CLOSE]
    assert caps.supported_time_in_force == [TimeInForce.FOK]
    assert caps.supported_sessions == [Session.POST_MARKET]
    assert caps.supported_quantity_units == [QuantityUnit.NOTIONAL]
    assert caps.base_currency is Currency.USD
    # Plugin explicitly turned analyzer off; default for IN_stock would
    # have been True. Explicit must win.
    assert caps.supports_analyzer is False
    assert caps.features == {"vip_only": True}


def test_infer_uses_plugin_name_for_display() -> None:
    d = infer_capabilities_from_legacy(
        {
            "Plugin Name": "Pretty Broker Name",
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["NSE"],
            "broker_type": "IN_stock",
        },
        broker_code="pretty",
    )
    assert d["broker_display_name"] == "Pretty Broker Name"


def test_infer_falls_back_to_broker_code_for_display() -> None:
    d = infer_capabilities_from_legacy(
        {
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["NSE"],
            "broker_type": "IN_stock",
        },
        broker_code="xyz",
    )
    assert d["broker_display_name"] == "xyz"


def test_infer_no_longer_defaults_to_in_stock_when_broker_type_missing() -> None:
    """Phase 1 T-04: the implicit ``broker_type='IN_stock'`` default for
    legacy India plugins has been removed. A plugin that explicitly
    declares ``supported_regions=["india"]`` but omits ``broker_type``
    now falls through to ``_common_defaults()`` (OTHER market family),
    not Indian defaults. Every shipped legacy plugin already declares
    broker_type explicitly, so this only affects synthetic test data.
    """
    d = infer_capabilities_from_legacy(
        {
            "supported_regions": ["india"],  # Phase 1 T-03: required explicit
            "supported_exchanges": ["NSE"],
            # broker_type intentionally omitted to verify T-04 removal
        },
        broker_code="legacy_plugin",
    )
    caps = BrokerCapabilities(**d)
    assert MarketFamily.IN_STOCK not in caps.market_families, (
        "Phase 1 T-04 removed the implicit IN_stock default for empty broker_type"
    )
    assert MarketFamily.OTHER in caps.market_families
    assert caps.supports_analyzer is False  # _common_defaults skeleton



def test_supported_regions_inferred_from_market_families() -> None:
    caps = _minimal_capabilities(market_families=[MarketFamily.US_STOCK, MarketFamily.EU_STOCK])
    assert caps.supported_regions == ["us", "eu"]


def test_supported_regions_explicit_override_wins() -> None:
    caps = _minimal_capabilities(
        market_families=[MarketFamily.US_STOCK],
        supported_regions=["custom_us_region"],
    )
    assert caps.supported_regions == ["custom_us_region"]


def test_infer_supported_regions_deduplicates_preserving_order() -> None:
    assert infer_supported_regions_from_market_families(
        [MarketFamily.US_STOCK, MarketFamily.US_STOCK, MarketFamily.UK_STOCK]
    ) == ["us", "uk"]
