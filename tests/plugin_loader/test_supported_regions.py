"""Region-aware broker capability metadata."""

from __future__ import annotations

from utils import plugin_loader


def test_loader_accepts_rich_supported_venue_codes_without_legacy_field(
    make_broker_tree, chdir, reset_loader_state
) -> None:
    make_broker_tree(
        {
            "schwab_like": {
                "Plugin Name": "Schwab Like",
                "broker_display_name": "Schwab Like",
                "market_families": ["US_STOCK"],
                "supported_venue_codes": ["XNYS", "XNAS"],
                "supported_asset_classes": ["EQUITY", "ETF"],
                "supported_order_types": ["MARKET", "LIMIT"],
                "supported_time_in_force": ["DAY", "GTC"],
                "supported_sessions": ["REGULAR", "PRE_MARKET", "POST_MARKET"],
                "supported_quantity_units": ["WHOLE", "FRACTIONAL"],
                "trading_currencies": ["USD"],
                "base_currency": "USD",
                "supports_fractional": True,
                "supports_extended_hours": True,
                "supports_short_selling": True,
            }
        }
    )

    caps = plugin_loader.load_broker_capabilities("broker")
    assert "schwab_like" in caps
    assert caps["schwab_like"].supported_venue_codes == ["XNYS", "XNAS"]


def test_supported_regions_inferred_from_market_families(
    make_broker_tree, chdir, reset_loader_state
) -> None:
    make_broker_tree(
        {
            "hybrid_us_uk": {
                "Plugin Name": "Hybrid",
                "supported_exchanges": ["XNYS", "XLON"],
                "broker_type": "IN_stock",
                "market_families": ["US_STOCK", "UK_STOCK"],
                "supported_venue_codes": ["XNYS", "XLON"],
                "supported_asset_classes": ["EQUITY"],
                "supported_order_types": ["MARKET", "LIMIT"],
                "supported_time_in_force": ["DAY"],
                "supported_sessions": ["REGULAR"],
                "supported_quantity_units": ["WHOLE"],
                "trading_currencies": ["USD", "GBP"],
            }
        }
    )

    caps = plugin_loader.load_broker_capabilities("broker")["hybrid_us_uk"]
    assert caps.supported_regions == ["us", "uk"]


def test_supported_regions_explicit_override_round_trips(
    make_broker_tree, chdir, reset_loader_state
) -> None:
    make_broker_tree(
        {
            "custom_region": {
                "Plugin Name": "Custom Region",
                # v4 Phase 4 (ADR 0025) required promoted fields.
                "broker_code": "custom_region",
                "broker_display_name": "Custom Region",
                "account_context_supports": ["account_id"],
                "supported_exchanges": ["XNAS"],
                "broker_type": "IN_stock",
                "market_families": ["US_STOCK"],
                "supported_regions": ["north_america"],
                "supported_venue_codes": ["XNAS"],
                "supported_asset_classes": ["EQUITY"],
                "supported_order_types": ["MARKET", "LIMIT"],
                "supported_time_in_force": ["DAY"],
                "supported_sessions": ["REGULAR"],
                "supported_quantity_units": ["WHOLE"],
                "trading_currencies": ["USD"],
                # default_currency is required by Phase 1 fail-closed
                # inference for any plugin whose supported_regions
                # excludes "india" (ADR 0006).
                "default_currency": "USD",
                "base_currency": "USD",
                # Phase 1 v3 (ADR 0017) — required for non-India plugins.
                "auth_modes": ["OAUTH"],
                "master_contract_refresh_policy": {
                    "timezone": "America/New_York",
                    "cutoff_local": "08:00",
                    "frequency": "daily",
                    "skip_if_24x7": False,
                },
            }
        }
    )

    caps = plugin_loader.load_broker_capabilities("broker")["custom_region"]
    assert caps.supported_regions == ["north_america"]
    dumped = caps.model_dump(mode="json")
    assert dumped["supported_regions"] == ["north_america"]
