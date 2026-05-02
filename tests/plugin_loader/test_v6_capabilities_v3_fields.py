"""Phase 0 (T-02) — broker capabilities v3 capability flags.

Asserts that:
* The 5 new optional fields exist on ``BrokerCapabilities`` with the
  correct safe-no-op defaults.
* ``infer_capabilities_from_legacy`` accepts and round-trips them via
  ``_EXPLICIT_OVERRIDE_KEYS``.
* All 35 shipped broker plugins still load and instantiate
  ``BrokerCapabilities`` without raising.

The fields exist so:
* Phase 5 can swap ``promoted_mpp_service``'s hardcoded broker
  frozensets for ``requires_market_price_protection`` /
  ``requires_slm_to_sl_conversion`` reads.
* Phase 5 can replace the WS router substring match with
  ``topic_format``.
* Phase 9 can gate v1 mounting per broker via ``requires_v1_compat``.
* Brokers reporting in minor units (paise / cents) can declare
  ``minor_unit_divisor``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.capabilities import (
    BrokerCapabilities,
    infer_capabilities_from_legacy,
)
from domain.enums import (
    AssetClass,
    MarketFamily,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)
from utils import plugin_loader


REPO_ROOT = Path(__file__).resolve().parents[2]


REQUIRED_V3_FIELDS_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("requires_market_price_protection", False),
    ("requires_slm_to_sl_conversion", False),
    ("minor_unit_divisor", None),
    ("topic_format", None),
    ("requires_v1_compat", False),
)


def _minimal_capability_payload() -> dict:
    return {
        "broker_code": "v3demo",
        "broker_display_name": "V3 demo broker",
        "market_families": [MarketFamily.OTHER],
        "supported_regions": ["us"],
        "supported_venue_codes": ["XNYS"],
        "supported_asset_classes": [AssetClass.EQUITY],
        "supported_order_types": [OrderType.MARKET, OrderType.LIMIT],
        "supported_time_in_force": [TimeInForce.DAY],
        "supported_sessions": [Session.REGULAR],
        "supported_quantity_units": [QuantityUnit.WHOLE],
        "trading_currencies": [],
    }


def test_v3_fields_present_with_safe_defaults() -> None:
    caps = BrokerCapabilities(**_minimal_capability_payload())
    for name, expected in REQUIRED_V3_FIELDS_DEFAULTS:
        actual = getattr(caps, name)
        assert actual == expected, (
            f"BrokerCapabilities.{name} default {actual!r} != expected {expected!r}"
        )


def test_v3_fields_round_trip_when_populated() -> None:
    payload = _minimal_capability_payload()
    payload.update(
        {
            "requires_market_price_protection": True,
            "requires_slm_to_sl_conversion": True,
            "minor_unit_divisor": 100,
            "topic_format": "venue_index:symbol",
            "requires_v1_compat": True,
        }
    )
    caps = BrokerCapabilities(**payload)
    dumped = caps.model_dump()
    rehydrated = BrokerCapabilities(**{
        k: v
        for k, v in dumped.items()
        # Skip computed fields — they are derived, not settable.
        if k not in {"broker_name", "broker_type", "supported_exchanges"}
    })
    for name, _ in REQUIRED_V3_FIELDS_DEFAULTS:
        assert getattr(rehydrated, name) == getattr(caps, name)


def test_infer_capabilities_round_trips_v3_fields_explicit_override() -> None:
    plugin_data = {
        "broker_type": "IN_stock",
        "supported_regions": ["india"],  # Phase 1 T-03: required explicit
        "Plugin Name": "ZerodhaTest",
        "supported_exchanges": ["NSE", "BSE"],
        # New v3 fields explicitly declared in plugin.json
        "requires_market_price_protection": True,
        "requires_slm_to_sl_conversion": False,
        "minor_unit_divisor": 100,
        "topic_format": "venue:symbol",
        "requires_v1_compat": True,
    }
    inferred = infer_capabilities_from_legacy(plugin_data, broker_code="zerodhatest")
    # The explicit values must flow through into the dict
    assert inferred["requires_market_price_protection"] is True
    assert inferred["requires_slm_to_sl_conversion"] is False
    assert inferred["minor_unit_divisor"] == 100
    assert inferred["topic_format"] == "venue:symbol"
    assert inferred["requires_v1_compat"] is True
    # And the resulting BrokerCapabilities still validates
    caps = BrokerCapabilities(**inferred)
    assert caps.requires_market_price_protection is True
    assert caps.minor_unit_divisor == 100
    assert caps.topic_format == "venue:symbol"


def test_infer_capabilities_legacy_india_keeps_safe_defaults() -> None:
    """A legacy India plugin that does NOT declare v3 fields gets safe defaults."""
    plugin_data = {
        "broker_type": "IN_stock",
        "supported_regions": ["india"],  # Phase 1 T-03: required explicit
        "Plugin Name": "LegacyIndiaTest",
        "supported_exchanges": ["NSE"],
    }
    inferred = infer_capabilities_from_legacy(plugin_data, broker_code="legacyindia")
    caps = BrokerCapabilities(**inferred)
    for name, expected in REQUIRED_V3_FIELDS_DEFAULTS:
        assert getattr(caps, name) == expected, (
            f"legacy India default for {name} drifted from {expected!r}"
        )


def test_all_shipped_broker_plugins_still_load() -> None:
    """Every plugin.json in broker/ must still load to a valid
    ``BrokerCapabilities`` after the v3 fields are added.

    This is the primary non-regression assertion for Phase 0 T-02.
    """
    plugin_loader.load_broker_capabilities()
    broker_root = REPO_ROOT / "broker"
    broker_codes = sorted(
        p.name
        for p in broker_root.iterdir()
        if p.is_dir() and (p / "plugin.json").exists()
    )
    assert broker_codes, "no broker plugin.json files discovered"
    failures: list[tuple[str, str]] = []
    for code in broker_codes:
        caps = plugin_loader.get_broker_capabilities(code)
        if caps is None:
            failures.append((code, "capabilities returned None"))
            continue
        # Sanity: new fields default safely (or are explicitly set in
        # plugin.json — both are acceptable).
        for name, _expected in REQUIRED_V3_FIELDS_DEFAULTS:
            assert hasattr(caps, name), (
                f"broker {code!r} capabilities missing {name}"
            )
    assert not failures, f"broker plugin load failures: {failures}"
