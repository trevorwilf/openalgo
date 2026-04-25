"""Phase 5 — /api/v2/regions endpoints."""

from __future__ import annotations

import pytest


def test_regions_list(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions")
    assert resp.status_code == 200
    body = resp.get_json()
    codes = {r["region_code"] for r in body["data"]["regions"]}
    # The shipped seeds always include India.
    assert "india" in codes
    assert {"us", "uk", "eu"} <= codes


def test_region_detail(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions/india")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["region_code"] == "india"
    # v2 shape includes venues and symbol_display.
    assert any(v["venue_code"] == "NSE" for v in body["data"]["venues"])
    assert body["data"]["symbol_display"]["date_format"] == "DDMMMYY"


def test_region_detail_404(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions/atlantis")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "region_not_found"


def test_region_flow_defaults_india(flask_app):
    resp = flask_app.test_client().get("/api/v2/regions/india/flow_defaults")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["flow_templates_enabled"] is True
    assert "MIS" in body["products"]
    assert "NIFTY" in body["option_underlyings"]


def test_region_flow_defaults_us_disabled(flask_app):
    """US region has flow_templates_enabled=false in its plugin →
    endpoint returns the disabled shape with empty lists."""
    resp = flask_app.test_client().get("/api/v2/regions/us/flow_defaults")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["flow_templates_enabled"] is False
    assert body["products"] == []
    assert body["exchanges"] == []
