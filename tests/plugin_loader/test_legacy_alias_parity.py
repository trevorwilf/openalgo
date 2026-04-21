"""For every real plugin.json, the rich-model legacy aliases
(`broker_name`, `broker_type`, `supported_exchanges`, `leverage_config`)
match exactly what the old shallow loader would have returned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.capabilities import BrokerCapabilities, infer_capabilities_from_legacy

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_PLUGINS = sorted((REPO_ROOT / "broker").glob("*/plugin.json"))


def _legacy_expected(plugin_data: dict, broker_name: str) -> dict:
    """Recreate the old shallow loader's return shape."""
    return {
        "broker_name": broker_name,
        "broker_type": plugin_data.get("broker_type", "IN_stock"),
        "supported_exchanges": plugin_data.get("supported_exchanges", []),
        "leverage_config": plugin_data.get("leverage_config", False),
    }


@pytest.mark.parametrize(
    "plugin_path", REAL_PLUGINS, ids=[p.parent.name for p in REAL_PLUGINS]
)
def test_alias_matches_legacy(plugin_path: Path) -> None:
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    if "supported_exchanges" not in data:
        pytest.skip("no supported_exchanges")

    broker_name = plugin_path.parent.name
    expected = _legacy_expected(data, broker_name)

    caps = BrokerCapabilities(**infer_capabilities_from_legacy(data, broker_name))
    dumped = caps.model_dump(mode="json")

    assert dumped["broker_name"] == expected["broker_name"]
    assert dumped["broker_type"] == expected["broker_type"]
    assert dumped["supported_exchanges"] == expected["supported_exchanges"]
    assert dumped["leverage_config"] == expected["leverage_config"]
