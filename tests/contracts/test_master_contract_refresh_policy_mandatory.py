"""T-09 — master_contract_refresh_policy mandatory for non-legacy plugins.

Phase 3 contract: any broker plugin whose ``supported_regions``
excludes ``"india"`` MUST declare ``master_contract_refresh_policy``
in its plugin.json. The legacy India plugins (with
``supported_regions=["india"]`` exactly) continue to allow
``None`` and fall through to the IST 08:00 behavior baked into
``utils/auth_utils.py``.

This test scans every plugin.json in ``broker/`` and asserts the
non-legacy plugins all declare a refresh policy. New non-India
broker plugins introduced after this commit will fail at load time
if they omit the field — this test is the static-side guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_BROKER_DIR = Path(__file__).resolve().parents[2] / "broker"


def _broker_plugins() -> list[Path]:
    return sorted(
        d / "plugin.json"
        for d in _BROKER_DIR.iterdir()
        if d.is_dir() and (d / "plugin.json").exists()
    )


def _is_legacy_india(plugin_data: dict) -> bool:
    regions = plugin_data.get("supported_regions") or []
    if not isinstance(regions, list):
        return False
    return {str(r).strip().lower() for r in regions} == {"india"}


@pytest.mark.parametrize(
    "plugin_path",
    _broker_plugins(),
    ids=lambda p: p.parent.name,
)
def test_non_legacy_plugin_has_refresh_policy(plugin_path: Path) -> None:
    with plugin_path.open(encoding="utf-8") as f:
        plugin_data = json.load(f)
    if _is_legacy_india(plugin_data):
        pytest.skip("legacy India plugin — refresh_policy optional")
    assert plugin_data.get("master_contract_refresh_policy"), (
        f"{plugin_path.parent.name}: non-legacy plugin must declare "
        "master_contract_refresh_policy in plugin.json. T-09 makes "
        "this mandatory; missing values raise BrokerCapabilityError "
        "at plugin load time."
    )
