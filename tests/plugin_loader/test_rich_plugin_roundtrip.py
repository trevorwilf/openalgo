"""A new-shape plugin.json preserves explicit values (not overwritten by defaults)."""

from __future__ import annotations

from utils import plugin_loader


def test_rich_plugin_preserved(
    make_broker_tree, chdir, reset_loader_state
) -> None:
    """Every new-shape field declared in plugin.json must round-trip intact."""
    make_broker_tree(
        {
            "hybrid": {
                "Plugin Name": "Hybrid Broker",
                "broker_type": "IN_stock",
                "supported_exchanges": ["NSE", "NFO"],
                "leverage_config": True,
                # Rich, explicit overrides:
                "market_families": ["IN_STOCK", "CRYPTO"],
                "supported_asset_classes": ["EQUITY", "SPOT"],
                "supported_order_types": ["MARKET", "LIMIT", "TRAILING_STOP"],
                "supported_time_in_force": ["DAY", "GTC"],
                "supported_sessions": ["REGULAR", "POST_MARKET"],
                "supported_quantity_units": ["WHOLE", "FRACTIONAL"],
                "trading_currencies": ["INR", "USDT"],
                "base_currency": "INR",
                "supports_fractional": True,
                "supports_notional_orders": True,
                "supports_extended_hours": True,
                "supports_short_selling": True,
                # Plugin explicitly turns OFF analyzer — default for IN_stock
                # would be True. Explicit must win.
                "supports_analyzer": False,
                "features": {"level2_depth": True, "after_hours_alerts": False},
            }
        }
    )

    caps = plugin_loader.load_broker_capabilities("broker")["hybrid"]

    # Explicit overrides
    assert [f.value for f in caps.market_families] == ["IN_STOCK", "CRYPTO"]
    assert [a.value for a in caps.supported_asset_classes] == ["EQUITY", "SPOT"]
    assert [o.value for o in caps.supported_order_types] == [
        "MARKET", "LIMIT", "TRAILING_STOP"
    ]
    assert [t.value for t in caps.supported_time_in_force] == ["DAY", "GTC"]
    assert [s.value for s in caps.supported_sessions] == ["REGULAR", "POST_MARKET"]
    assert [q.value for q in caps.supported_quantity_units] == ["WHOLE", "FRACTIONAL"]
    assert [c.value for c in caps.trading_currencies] == ["INR", "USDT"]
    assert caps.base_currency.value == "INR"
    assert caps.supports_fractional is True
    assert caps.supports_notional_orders is True
    assert caps.supports_extended_hours is True
    assert caps.supports_short_selling is True
    # Explicit OFF — must win over IN_stock default of True
    assert caps.supports_analyzer is False
    assert caps.features == {"level2_depth": True, "after_hours_alerts": False}

    # Legacy aliases still work
    assert caps.broker_type == "IN_stock"  # IN_STOCK present anywhere wins
    assert caps.supported_exchanges == ["NSE", "NFO"]
    assert caps.broker_name == "hybrid"
    assert caps.broker_display_name == "Hybrid Broker"

    # model_dump(mode="json") exposes all keys including legacy aliases
    d = caps.model_dump(mode="json")
    assert d["broker_name"] == "hybrid"
    assert d["broker_type"] == "IN_stock"
    assert d["supported_exchanges"] == ["NSE", "NFO"]
    assert d["leverage_config"] is True
    assert d["supports_analyzer"] is False
    assert d["features"] == {"level2_depth": True, "after_hours_alerts": False}
