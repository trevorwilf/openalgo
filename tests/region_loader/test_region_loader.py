"""Market-region plugin loading and schema enforcement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import region_loader

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_REGION_PLUGINS = sorted((REPO_ROOT / "market_regions").glob("*/plugin.json"))


@pytest.mark.parametrize(
    "plugin_path", REAL_REGION_PLUGINS, ids=[p.parent.name for p in REAL_REGION_PLUGINS]
)
def test_real_region_plugins_pass_schema(plugin_path: Path) -> None:
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    errors = region_loader._validate_plugin_json(data)
    assert errors == [], f"{plugin_path.parent.name} plugin.json failed schema: {errors}"


def test_region_loader_loads_valid_plugins(make_region_tree, chdir, reset_loader_state) -> None:
    make_region_tree(
        {
            "us": {
                "display_name": "United States",
                "timezone_name": "America/New_York",
                "market_families": ["US_STOCK"],
                "default_currency": "USD",
                "default_venue_codes": ["XNYS", "XNAS"],
                "default_sessions": ["REGULAR"],
                "country_codes": ["US"],
            }
        }
    )

    regions = region_loader.load_market_regions("market_regions")
    assert list(regions) == ["us"]
    assert regions["us"].region_code == "us"
    assert regions["us"].default_venue_codes == ["XNYS", "XNAS"]


def test_region_loader_skips_invalid_shape_without_crash(
    make_region_tree, chdir, reset_loader_state, caplog
) -> None:
    make_region_tree(
        {
            "good": {
                "display_name": "India",
                "timezone_name": "Asia/Kolkata",
                "market_families": ["IN_STOCK"],
            },
            "bad": {
                "display_name": "Broken",
                "timezone_name": 123,
                "market_families": ["IN_STOCK"],
            },
        }
    )

    with caplog.at_level("ERROR"):
        regions = region_loader.load_market_regions("market_regions")

    assert "good" in regions
    assert "bad" not in regions
    assert "bad" in region_loader._skipped_regions_for_tests()


def test_region_code_defaults_from_directory_name(make_region_tree, chdir, reset_loader_state) -> None:
    make_region_tree(
        {
            "uk": {
                "display_name": "United Kingdom",
                "timezone_name": "Europe/London",
                "market_families": ["UK_STOCK"],
            }
        }
    )

    regions = region_loader.load_market_regions("market_regions")
    assert regions["uk"].region_code == "uk"
