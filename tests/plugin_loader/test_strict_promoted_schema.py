"""Phase 4 v4 (ADR 0025) — promoted plugin strict-mode validator tests.

Each test exercises one branch of the strict-mode rules:

* Promoted plugin missing a required v4 field → skipped.
* Promoted plugin with an unknown field → skipped.
* Legacy India plugin missing optional fields → loaded with warning
  (or loaded silently if completeness-check passes).
* Mock Schwab / Webull / Alpaca pass strict mode (declared in their
  per-broker compliance tests; this file confirms the strict-mode
  helper directly).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alpaca_plugin_dict() -> dict:
    return json.loads(
        (REPO_ROOT / "broker" / "alpaca" / "plugin.json").read_text(encoding="utf-8")
    )


def _india_plugin_dict() -> dict:
    return {
        "Plugin Name": "test_india_broker",
        "broker_type": "IN_stock",
        "supported_exchanges": ["NSE", "BSE"],
    }


def test_alpaca_passes_strict_mode():
    errors = plugin_loader._strict_promoted_plugin_errors(
        "alpaca", _alpaca_plugin_dict()
    )
    assert errors == [], f"Alpaca should pass strict mode, got: {errors}"


def test_mock_schwab_passes_strict_mode():
    data = json.loads(
        (REPO_ROOT / "broker" / "_mock_schwab_like" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    errors = plugin_loader._strict_promoted_plugin_errors(
        "_mock_schwab_like", data
    )
    assert errors == [], f"_mock_schwab_like should pass strict mode, got: {errors}"


def test_mock_webull_passes_strict_mode():
    data = json.loads(
        (REPO_ROOT / "broker" / "_mock_webull_like" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    errors = plugin_loader._strict_promoted_plugin_errors(
        "_mock_webull_like", data
    )
    assert errors == [], f"_mock_webull_like should pass strict mode, got: {errors}"


def test_legacy_india_plugin_skips_strict_mode():
    """Legacy India plugins (no supported_regions or supported_regions=['india'])
    are not strict-checked at all."""
    errors = plugin_loader._strict_promoted_plugin_errors(
        "test_india_broker", _india_plugin_dict()
    )
    assert errors == [], "Legacy India plugins should bypass strict mode"


def test_promoted_plugin_missing_required_field_fails():
    data = _alpaca_plugin_dict()
    del data["broker_code"]
    errors = plugin_loader._strict_promoted_plugin_errors("alpaca", data)
    assert errors, "Missing broker_code must fail strict mode"
    assert any("broker_code" in e for e in errors)


def test_promoted_plugin_unknown_field_fails():
    data = _alpaca_plugin_dict()
    data["this_is_not_a_known_field"] = "oops"
    errors = plugin_loader._strict_promoted_plugin_errors("alpaca", data)
    assert errors, "Unknown field must fail strict mode"
    assert any("this_is_not_a_known_field" in e for e in errors)


def test_promoted_marker_explicitly_promotes():
    """A plugin with supported_regions=['india', 'us'] AND promoted=true
    is treated as promoted (strict-checked)."""
    data = {
        "Plugin Name": "explicit_promoted",
        "supported_regions": ["india", "us"],
        "promoted": True,
        "broker_type": "MULTI",
    }
    errors = plugin_loader._strict_promoted_plugin_errors(
        "explicit_promoted", data
    )
    assert errors, "Explicit promoted marker must trigger strict mode"
