"""Phase 3 v6 — capability load multi-region smoke test.

Verifies that each of the four region plugins (india, us, eu, uk)
resolves to a region plugin object with non-empty venues, currencies,
sessions, and timezone metadata.

This is the framework-completeness smoke test — at v6 close, every
region must declare enough metadata for the rest of the platform to
treat it as a first-class region.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGION_ROOT = REPO_ROOT / "market_regions"
REGIONS = ("india", "us", "eu", "uk")


@pytest.mark.parametrize("region_code", REGIONS)
def test_region_plugin_file_exists(region_code: str) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    assert p.is_file(), f"missing region plugin for {region_code!r}: {p}"


@pytest.mark.parametrize("region_code", REGIONS)
def test_region_plugin_declares_required_fields(region_code: str) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for field_name in (
        "region_code",
        "display_name",
        "timezone_name",
        "default_currency",
        "default_venue_codes",
        "venues",
        "session_templates",
        "symbol_display",
    ):
        assert field_name in data, (
            f"region {region_code!r} missing field {field_name!r}"
        )


@pytest.mark.parametrize("region_code", REGIONS)
def test_region_plugin_venues_are_non_empty(region_code: str) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    venues = data.get("venues") or []
    assert len(venues) >= 1, f"region {region_code!r} has empty venues list"
    for v in venues:
        for venue_field in (
            "venue_code", "display_name", "timezone_name", "base_currency",
        ):
            assert venue_field in v, (
                f"region {region_code!r} venue missing {venue_field!r}: {v}"
            )


@pytest.mark.parametrize(
    ("region_code", "expected_currency"),
    [("india", "INR"), ("us", "USD"), ("eu", "EUR"), ("uk", "GBP")],
)
def test_region_currency_is_correct(region_code: str, expected_currency: str) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["default_currency"] == expected_currency


@pytest.mark.parametrize(
    ("region_code", "expected_tz"),
    [
        ("india", "Asia/Kolkata"),
        ("us", "America/New_York"),
        ("eu", "Europe/Paris"),
        ("uk", "Europe/London"),
    ],
)
def test_region_timezone_is_correct(region_code: str, expected_tz: str) -> None:
    p = REGION_ROOT / region_code / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["timezone_name"] == expected_tz
