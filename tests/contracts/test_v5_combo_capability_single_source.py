"""Phase 7 v5 — combo type capability single-source contract.

Both experts flagged drift between top-level
``BrokerCapabilities.supports_combo_types`` (read by
``restx_api/v2/orders_combo.py``) and
``ProductCapabilities.supports_combo_types`` (per-asset). v5 Phase 7
makes the **top-level** the canonical source and keeps the per-asset
field as an asset-class-scoped override.

Contract:

* ``BrokerCapabilities.supports_combo_types`` exists at the top level
  and accepts ``ComboType`` values.
* ``ProductCapabilities.supports_combo_types`` still exists for
  per-asset overrides.
* The mock plugin JSONs that previously declared the field at top
  level now round-trip through the loader without losing it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_top_level_supports_combo_types_field_exists():
    """Top-level ``BrokerCapabilities.supports_combo_types`` is a model field."""
    from domain.capabilities import BrokerCapabilities, ComboType, MarketFamily, Currency

    caps = BrokerCapabilities(
        broker_code="x",
        broker_display_name="X",
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
        supports_combo_types=[ComboType.OCO, ComboType.OTO],
    )
    assert ComboType.OCO in caps.supports_combo_types
    assert ComboType.OTO in caps.supports_combo_types


def test_per_product_supports_combo_types_field_still_exists():
    """``ProductCapabilities.supports_combo_types`` retained for per-asset override."""
    from domain.capabilities import AssetClass, ComboType, ProductCapabilities

    pc = ProductCapabilities(
        asset_class=AssetClass.OPTION,
        supports_combo_types=[ComboType.OCO],
    )
    assert ComboType.OCO in pc.supports_combo_types


def test_top_level_default_is_empty_list():
    from domain.capabilities import BrokerCapabilities, MarketFamily, Currency

    caps = BrokerCapabilities(
        broker_code="x",
        broker_display_name="X",
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
    )
    assert caps.supports_combo_types == []


@pytest.mark.parametrize(
    "plugin_path",
    [
        REPO_ROOT / "broker" / "_mock_schwab_like" / "plugin.json",
        REPO_ROOT / "broker" / "_mock_webull_like" / "plugin.json",
    ],
)
def test_mock_plugins_declare_combo_types_at_top_level(plugin_path):
    """The framework-readiness mock plugins are the canonical examples
    of how a non-India broker plugin should look. Both must declare
    ``supports_combo_types`` at the top level (not inside ``products``)
    so the v2 combo dispatcher gate fires."""
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    assert "supports_combo_types" in plugin, (
        f"{plugin_path.name}: top-level supports_combo_types missing — the "
        "v2 combo capability gate keys off this field."
    )
    val = plugin["supports_combo_types"]
    assert isinstance(val, list) and val, (
        f"{plugin_path.name}: supports_combo_types must be a non-empty list."
    )


def test_orders_combo_route_reads_top_level_field():
    """``restx_api/v2/orders_combo.py`` reads ``caps.supports_combo_types``
    (top-level) — not ``caps.products[*].supports_combo_types``. The
    contract test pins the read so a future refactor that switches to
    per-asset reads must update this test deliberately."""
    text = (REPO_ROOT / "restx_api" / "v2" / "orders_combo.py").read_text(
        encoding="utf-8"
    )
    assert 'getattr(caps, "supports_combo_types"' in text or (
        'caps.supports_combo_types' in text
    ), (
        "v2 combo route must read the top-level supports_combo_types field. "
        "If the read moved per-asset, update this contract test."
    )
