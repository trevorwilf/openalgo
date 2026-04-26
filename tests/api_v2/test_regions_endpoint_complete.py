"""Phase 5 v3 (ADR 0021) — region API completeness assertions.

The v2 prompt's Phase 5 had already shipped most of the
``/api/v2/regions/*`` surface; this test pins the response shape so
future code cannot quietly drop fields the frontend relies on.

Required shape per ADR 0021 / expert 1 §3.4:

GET /api/v2/regions/<code> returns:

* region_code
* display_name
* country_codes
* default_currency
* default_timezone (== timezone_name)
* market_families
* default_venue_codes
* default_sessions
* venues (list of venue records)
* session_templates (list)
* calendar_exceptions (list)
* symbol_display (object)
* feature_flags (object)
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _ensure_regions_loaded():
    """The region loader cache is global; tests that run before any
    other region-touching test see an empty cache. Force-load it."""
    from utils import region_loader

    repo_root = Path(__file__).resolve().parents[2]
    region_loader._reset_cache_for_tests()
    region_loader.load_market_regions(str(repo_root / "market_regions"))
    yield
    region_loader._reset_cache_for_tests()

REQUIRED_REGION_FIELDS = (
    "region_code",
    "display_name",
    "country_codes",
    "default_currency",
    "timezone_name",
    "market_families",
    "default_venue_codes",
    "default_sessions",
    "venues",
    "session_templates",
    "calendar_exceptions",
    "symbol_display",
    "feature_flags",
)


@pytest.mark.parametrize("region_code", ["india", "us", "uk", "eu"])
def test_region_detail_returns_complete_shape(flask_app, region_code):
    resp = flask_app.test_client().get(f"/api/v2/regions/{region_code}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    missing = [f for f in REQUIRED_REGION_FIELDS if f not in body]
    assert not missing, f"region {region_code!r} missing fields: {missing}"


def test_region_detail_field_types(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions/india")
    body = resp.get_json()["data"]
    assert isinstance(body["region_code"], str)
    assert isinstance(body["country_codes"], list)
    assert isinstance(body["market_families"], list)
    assert isinstance(body["default_venue_codes"], list)
    assert isinstance(body["venues"], list)
    assert isinstance(body["session_templates"], list)
    assert isinstance(body["calendar_exceptions"], list)
    assert isinstance(body["symbol_display"], dict)
    assert isinstance(body["feature_flags"], dict)


def test_region_list_includes_all_seeded(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions")
    body = resp.get_json()["data"]
    codes = {r["region_code"] for r in body["regions"]}
    assert {"india", "us", "uk", "eu"} <= codes


def test_region_flow_defaults_india_full_shape(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions/india/flow_defaults")
    body = resp.get_json()["data"]
    assert "exchanges" in body
    assert "products" in body
    assert "option_underlyings" in body
    assert "lot_sizes" in body
    assert "schedule_default" in body


def test_region_flow_defaults_non_india_returns_disabled_shape(flask_app):
    """Non-India region without flow_templates_enabled returns the
    'disabled' empty shape so the frontend knows to render an
    'unavailable' state instead of an India template."""
    for region in ("us", "uk", "eu"):
        resp = flask_app.test_client().get(f"/api/v2/regions/{region}/flow_defaults")
        body = resp.get_json()["data"]
        # Either the region's flow_templates_enabled is false (disabled
        # shape) or it has its own non-empty defaults — both forms are
        # valid; the contract is that exchanges/products are arrays.
        assert isinstance(body["exchanges"], list)
        assert isinstance(body["products"], list)
