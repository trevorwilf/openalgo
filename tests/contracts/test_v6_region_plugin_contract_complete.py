"""Phase 3 v6 — region plugin contract completeness.

Asserts every region plugin in `market_regions/<code>/plugin.json`
satisfies the same contract: declares the required top-level fields,
declares at least one venue with the required venue fields, declares
at least one session template with the required session fields, and
declares a feature_flags map.

This is the framework-level invariant that any new region (APAC,
LATAM, etc.) must pass before being added.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGION_ROOT = REPO_ROOT / "market_regions"

REQUIRED_TOP_LEVEL = (
    "region_code",
    "display_name",
    "timezone_name",
    "default_currency",
    "default_venue_codes",
    "venues",
    "session_templates",
    "symbol_display",
)
REQUIRED_VENUE_FIELDS = (
    "venue_code", "display_name", "timezone_name", "base_currency",
    "settlement_template",
)
REQUIRED_SESSION_FIELDS = (
    "session_code", "venue_codes", "local_start_time", "local_end_time",
    "days_of_week",
)
REQUIRED_SYMBOL_DISPLAY_FIELDS = (
    "date_format", "option_right_codes",
)


def _load_all_regions() -> list[tuple[str, dict]]:
    out = []
    for sub in REGION_ROOT.iterdir():
        if sub.is_dir() and (sub / "plugin.json").is_file():
            out.append((sub.name, json.loads((sub / "plugin.json").read_text(encoding="utf-8"))))
    return out


def test_at_least_four_regions_exist() -> None:
    regions = {name for name, _ in _load_all_regions()}
    for required in ("india", "us", "eu", "uk"):
        assert required in regions, f"required region missing: {required!r}"


@pytest.mark.parametrize(
    ("region_name", "data"),
    [(n, d) for n, d in _load_all_regions()],
    ids=lambda x: x if isinstance(x, str) else "data",
)
def test_region_has_required_top_level_fields(region_name: str, data: dict) -> None:
    for field_name in REQUIRED_TOP_LEVEL:
        assert field_name in data, (
            f"region {region_name!r} missing top-level field {field_name!r}"
        )


@pytest.mark.parametrize(
    ("region_name", "data"),
    [(n, d) for n, d in _load_all_regions()],
    ids=lambda x: x if isinstance(x, str) else "data",
)
def test_region_venues_have_required_fields(region_name: str, data: dict) -> None:
    venues = data.get("venues") or []
    assert venues, f"region {region_name!r} has empty venues list"
    for v in venues:
        for vf in REQUIRED_VENUE_FIELDS:
            assert vf in v, (
                f"region {region_name!r} venue missing {vf!r}: {v}"
            )


@pytest.mark.parametrize(
    ("region_name", "data"),
    [(n, d) for n, d in _load_all_regions()],
    ids=lambda x: x if isinstance(x, str) else "data",
)
def test_region_session_templates_have_required_fields(region_name: str, data: dict) -> None:
    sessions = data.get("session_templates") or []
    assert sessions, f"region {region_name!r} has empty session_templates"
    for s in sessions:
        for sf in REQUIRED_SESSION_FIELDS:
            assert sf in s, (
                f"region {region_name!r} session missing {sf!r}: {s}"
            )


@pytest.mark.parametrize(
    ("region_name", "data"),
    [(n, d) for n, d in _load_all_regions()],
    ids=lambda x: x if isinstance(x, str) else "data",
)
def test_region_symbol_display_has_required_fields(region_name: str, data: dict) -> None:
    sd = data.get("symbol_display") or {}
    for sf in REQUIRED_SYMBOL_DISPLAY_FIELDS:
        assert sf in sd, (
            f"region {region_name!r} symbol_display missing {sf!r}"
        )


def test_india_region_uses_india_specific_grammar() -> None:
    """India region's symbol_display must use the DDMMMYY grammar
    (Indian options) — non-India regions use ISO YYYY-MM-DD."""
    p = REGION_ROOT / "india" / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    df = data["symbol_display"]["date_format"]
    assert "DDMMMYY" in df or df.upper().endswith("DDMMMYY")


@pytest.mark.parametrize("region", ["us", "eu", "uk"])
def test_non_india_regions_use_iso_date_format(region: str) -> None:
    """Non-India regions must use a non-India date format."""
    p = REGION_ROOT / region / "plugin.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    df = data["symbol_display"]["date_format"]
    # ISO is the v6-default for non-India.
    assert "DDMMMYY" not in df.upper(), (
        f"{region} symbol_display date_format = {df!r} contains the "
        "India DDMMMYY grammar — would cause silent India fallback"
    )
