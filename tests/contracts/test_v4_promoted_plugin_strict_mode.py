"""v4 invariant 6 — promoted broker plugins MUST validate strictly.

Strict mode is enabled by Phase 4. Until then this test is xfail; once
Phase 4 lands, the ``xfail`` marker is removed and the test asserts
the contract.

Strict mode means:

* ``additionalProperties: false`` for promoted plugin JSON.
* All v4 required promoted fields present:
  ``broker_code``, ``broker_display_name``, ``broker_type``,
  ``supported_regions``, ``market_families``, ``supported_venue_codes``,
  ``supported_asset_classes``, ``supported_order_types``,
  ``supported_time_in_force``, ``supported_sessions``,
  ``supported_quantity_units``, ``trading_currencies``,
  ``default_currency``, ``base_currency``, ``auth_modes``,
  ``account_context_supports``, ``master_contract_refresh_policy``.

Legacy India brokers (those whose ``supported_regions`` contains
``"india"`` and who do NOT set ``promoted: true``) keep the existing
non-strict mode for backward compatibility.

Phase 4 of v4 wires:

* ``utils/plugin_loader.py`` — strict validator gate for promoted plugins.
* ``docs/plugin-schema/plugin.schema.json`` — JSON schema with
  ``additionalProperties: false``.
* This test stops being xfail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


V4_REQUIRED_PROMOTED_FIELDS: set[str] = {
    "broker_code",
    "broker_display_name",
    "broker_type",
    "supported_regions",
    "market_families",
    "supported_venue_codes",
    "supported_asset_classes",
    "supported_order_types",
    "supported_time_in_force",
    "supported_sessions",
    "supported_quantity_units",
    "trading_currencies",
    "default_currency",
    "base_currency",
    "auth_modes",
    "account_context_supports",
    "master_contract_refresh_policy",
}


def _is_promoted_plugin(plugin_path: Path) -> bool:
    """A broker plugin is promoted if its directory contains a PROMOTED
    sentinel OR its ``supported_regions`` excludes ``"india"``."""
    sentinel = plugin_path.parent / "PROMOTED"
    if sentinel.exists():
        return True
    try:
        data = json.loads(plugin_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    regions = data.get("supported_regions") or []
    if not isinstance(regions, list):
        return False
    return regions and "india" not in [str(r).lower() for r in regions]


def _iter_promoted_plugin_jsons() -> list[Path]:
    broker_root = REPO_ROOT / "broker"
    out: list[Path] = []
    if not broker_root.is_dir():
        return out
    for d in broker_root.iterdir():
        if not d.is_dir():
            continue
        plugin = d / "plugin.json"
        if not plugin.is_file():
            continue
        if _is_promoted_plugin(plugin):
            out.append(plugin)
    return out


@pytest.mark.xfail(
    reason=(
        "v4 Phase 1: contract test installed; Phase 4 enforces strict mode "
        "in utils/plugin_loader.py and adds the JSON schema with "
        "additionalProperties:false."
    ),
    strict=False,
)
def test_promoted_plugins_have_all_v4_required_fields() -> None:
    plugins = _iter_promoted_plugin_jsons()
    assert plugins, "expected at least one promoted broker plugin"
    missing: list[str] = []
    for plugin in plugins:
        data = json.loads(plugin.read_text(encoding="utf-8"))
        for field in V4_REQUIRED_PROMOTED_FIELDS:
            if field not in data:
                missing.append(f"{plugin.relative_to(REPO_ROOT).as_posix()}: missing {field!r}")
    assert not missing, (
        "v4 invariant 6 violated — promoted plugins missing required fields:\n  "
        + "\n  ".join(missing)
    )
