"""broker/alpaca/plugin.json — schema-valid + declares US market."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "broker" / "alpaca" / "plugin.json"
SCHEMA = REPO_ROOT / "docs" / "plugin-schema" / "plugin.schema.json"


def test_plugin_file_exists():
    assert PLUGIN.is_file()


def test_plugin_is_valid_json():
    json.loads(PLUGIN.read_text(encoding="utf-8"))


def test_plugin_schema_validates():
    pytest.importorskip("jsonschema")
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_plugin_declares_us_region():
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert "us" in data.get("supported_regions", [])


def test_plugin_declares_us_stock_market_family():
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert "US_STOCK" in data.get("market_families", [])


def test_plugin_declares_xnas_and_xnys():
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    venues = data.get("supported_venue_codes", [])
    assert "XNAS" in venues
    assert "XNYS" in venues


def test_plugin_supports_fractional_and_notional():
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert data["supports_fractional"] is True
    assert data["supports_notional_orders"] is True


def test_plugin_enables_extended_hours():
    """Branch K — PRE_MARKET / POST_MARKET / EXTENDED sessions are
    supported via Alpaca's ``extended_hours`` flag, gated on
    type=LIMIT + TIF=DAY at the translator. Manifest declares the
    capability.
    """
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert data["supports_extended_hours"] is True
    assert "PRE_MARKET" in data["supported_sessions"]
    assert "POST_MARKET" in data["supported_sessions"]
