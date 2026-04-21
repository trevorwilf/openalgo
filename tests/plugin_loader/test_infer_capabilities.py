"""Every existing plugin.json must produce a well-formed BrokerCapabilities.

Parametrized over all broker/*/plugin.json files in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.capabilities import BrokerCapabilities, infer_capabilities_from_legacy

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_PLUGINS = sorted((REPO_ROOT / "broker").glob("*/plugin.json"))


def test_at_least_one_plugin_exists() -> None:
    assert len(REAL_PLUGINS) >= 1, "no broker/*/plugin.json files found"


@pytest.mark.parametrize(
    "plugin_path", REAL_PLUGINS, ids=[p.parent.name for p in REAL_PLUGINS]
)
def test_plugin_produces_valid_capabilities(plugin_path: Path) -> None:
    plugin_data = json.loads(plugin_path.read_text(encoding="utf-8"))
    if "supported_exchanges" not in plugin_data:
        pytest.skip(f"{plugin_path.parent.name} has no supported_exchanges")

    inferred = infer_capabilities_from_legacy(
        plugin_data, broker_code=plugin_path.parent.name
    )
    caps = BrokerCapabilities(**inferred)

    # Required invariants
    assert caps.broker_code == plugin_path.parent.name
    assert caps.broker_display_name  # non-empty
    assert caps.market_families
    assert caps.supported_asset_classes
    assert caps.supported_order_types
    assert caps.supported_time_in_force
    assert caps.supported_sessions
    assert caps.supported_quantity_units
    # supported_venue_codes mirrors legacy supported_exchanges
    assert caps.supported_venue_codes == plugin_data["supported_exchanges"]
