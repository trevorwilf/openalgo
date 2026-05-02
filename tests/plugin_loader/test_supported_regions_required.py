"""Phase 1 (T-03) — supported_regions is required for non-legacy plugins.

After the one-time migration commit (which added explicit
``supported_regions=["india"]`` to every legacy India plugin) and
the discriminator tightening (a plugin without ``supported_regions``
is no longer auto-classified as legacy India), a non-legacy plugin
manifest that omits the field must raise ``BrokerCapabilityError``
during inference. This test pins that contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.capabilities import (
    _is_legacy_india_plugin,
    infer_capabilities_from_legacy,
)
from domain.errors import BrokerCapabilityError
from utils import plugin_loader


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_shipped_broker_plugin_declares_supported_regions() -> None:
    """All 35 shipped broker plugins must ship with explicit
    supported_regions after the Phase 1 T-03 migration.
    """
    broker_root = REPO_ROOT / "broker"
    for p in sorted(broker_root.iterdir()):
        if not p.is_dir():
            continue
        pj = p / "plugin.json"
        if not pj.exists():
            continue
        data = json.loads(pj.read_text(encoding="utf-8"))
        assert "supported_regions" in data, (
            f"broker {p.name!r} plugin.json missing supported_regions "
            f"after Phase 1 T-03 migration"
        )
        regions = data["supported_regions"]
        assert isinstance(regions, list) and regions, (
            f"broker {p.name!r} supported_regions must be a non-empty list"
        )


def test_legacy_india_discriminator_no_longer_grandfathers_missing_field() -> None:
    """Phase 1 T-03 tightens the discriminator: a plugin without
    supported_regions is no longer treated as legacy India.
    """
    plugin_data = {"broker_type": "IN_stock"}  # no supported_regions
    assert _is_legacy_india_plugin(plugin_data) is False, (
        "after T-03 migration, missing supported_regions must NOT be "
        "treated as legacy India"
    )


def test_legacy_india_discriminator_recognizes_explicit_india_only() -> None:
    """A plugin that explicitly declares ``supported_regions=["india"]``
    is legacy India; declaring any non-India region drops out of legacy.
    """
    assert _is_legacy_india_plugin({"supported_regions": ["india"]}) is True
    assert _is_legacy_india_plugin({"supported_regions": ["INDIA"]}) is True  # case-insensitive
    assert _is_legacy_india_plugin({"supported_regions": ["us"]}) is False
    assert _is_legacy_india_plugin({"supported_regions": ["india", "us"]}) is False


def test_non_legacy_plugin_without_supported_regions_raises() -> None:
    """A synthetic plugin manifest that omits supported_regions and
    is no longer auto-classified as legacy India must raise
    ``BrokerCapabilityError`` from
    ``_check_explicit_fields_for_non_india`` (since broker_type,
    market_families, default_currency, base_currency are also missing).
    """
    plugin_data = {
        "Plugin Name": "synthetic-no-regions",
        # no supported_regions, no broker_type, no market_families
    }
    with pytest.raises(BrokerCapabilityError):
        infer_capabilities_from_legacy(plugin_data, broker_code="synthetic")


def test_no_implicit_in_stock_default_for_empty_broker_type() -> None:
    """Phase 1 T-04: an empty broker_type no longer routes to
    _indian_defaults() implicitly. Legacy India plugins still work
    because they explicitly declare broker_type="IN_stock".
    """
    plugin_data = {
        "supported_regions": ["india"],
        # no broker_type — empty string default no longer means IN_stock
        "supported_exchanges": ["NSE"],
    }
    inferred = infer_capabilities_from_legacy(plugin_data, broker_code="empty_btype")
    # _common_defaults returns supports_analyzer=False (Indian defaults
    # would have set True). This is the discriminator that catches
    # accidental India fallthrough.
    assert inferred.get("supports_analyzer") is False
    # IN_stock would have populated MarketFamily.IN_STOCK
    from domain.enums import MarketFamily

    assert MarketFamily.IN_STOCK not in inferred.get("market_families", []), (
        "empty broker_type must NOT route to IN_stock defaults"
    )


def test_all_35_brokers_still_load_after_t04_default_removal() -> None:
    """Bit-identical broker loading after T-04. Every shipped plugin
    explicitly declares broker_type so removing the implicit default
    is non-breaking.
    """
    plugin_loader.load_broker_capabilities()
    broker_root = REPO_ROOT / "broker"
    broker_codes = sorted(
        p.name
        for p in broker_root.iterdir()
        if p.is_dir() and (p / "plugin.json").exists()
    )
    for code in broker_codes:
        caps = plugin_loader.get_broker_capabilities(code)
        assert caps is not None, f"broker {code!r} failed to load after T-04"
