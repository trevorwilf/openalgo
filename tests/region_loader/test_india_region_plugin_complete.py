"""Phase 7a — IndiaRegionPlugin completeness.

Asserts every method on the :class:`RegionPlugin` Protocol returns
non-empty, byte-identical data when delegated through the new India
plugin class. The Phase 2 byte-identical fixture tests pin the data
itself; this test pins the **wiring**.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset(reset_loader_state):
    yield


def test_india_region_plugin_satisfies_protocol():
    from domain.region_plugin import RegionPlugin
    from market_regions.india.plugin import IndiaRegionPlugin

    plugin = IndiaRegionPlugin()
    # ``runtime_checkable`` Protocol — duck-type check.
    assert isinstance(plugin, RegionPlugin)


def test_india_plugin_resolves_via_region_loader():
    from utils import region_loader

    region_loader._reset_cache_for_tests()
    region_loader.load_market_regions()
    plugin = region_loader.get_region_plugin("india")
    assert plugin is not None
    assert plugin.region_code == "india"


def test_india_plugin_methods_return_non_empty():
    from market_regions.india.plugin import IndiaRegionPlugin

    plugin = IndiaRegionPlugin()
    # Manifest
    manifest = plugin.manifest()
    assert manifest.region_code == "india"
    assert len(manifest.venues) >= 6  # NSE/BSE/NFO/BFO/CDS/MCX at minimum
    # Timezone object identity — same instance everywhere
    import pytz

    assert plugin.timezone_object() is pytz.timezone("Asia/Kolkata")
    # Calendar
    holidays = plugin.holiday_calendar(2026)
    assert len(holidays) == 17  # 17 entries: 16 holidays + 1 SPECIAL_SESSION
    # Sessions
    assert len(plugin.session_templates()) >= 3
    # Squareoff rules
    rules = plugin.squareoff_rules()
    assert len(rules) == 8  # NSE/BSE/NFO/BFO/CDS/BCD/MCX/NCDEX
    # Qty-freeze
    freezes = plugin.qty_freeze_rules()
    assert len(freezes) == 1
    assert freezes[0]["venue"] == "NFO"
    # Options grammar
    grammar = plugin.options_grammar()
    assert grammar["date_format"] == "%d%b%y"
    assert grammar["right_codes"] == {"CE": "CALL", "PE": "PUT"}
    # Index classification
    idx = plugin.index_classification()
    assert idx == {"NSE": ["NSE_INDEX"], "BSE": ["BSE_INDEX"]}
    # Locale
    locale = plugin.locale()
    assert locale["currency"] == "INR"
    assert locale["symbol"] == "₹"
    # Settlement
    assert plugin.settlement_template("NSE") == "T+1"
    assert plugin.settlement_template("MCX") == "T+1"
    # Providers
    sb = plugin.sandbox_provider()
    assert sb.region_code == "india"
    op = plugin.options_provider()
    assert op.region_code == "india"
    # Screeners
    screeners = plugin.screener_providers()
    assert screeners == ["chartink"]


def test_india_plugin_holiday_calendar_year_outside_relocation_returns_empty():
    """The Phase 2 relocation only ships the 2026 calendar. Future
    years (2027+) must return an empty list — fail-soft, not raise —
    because adding new years is a region-data update, not a code
    change."""
    from market_regions.india.plugin import IndiaRegionPlugin

    plugin = IndiaRegionPlugin()
    assert plugin.holiday_calendar(2030) == []


def test_india_plugin_options_grammar_returns_deep_copy():
    """Mutating the returned dict must not affect the source-of-truth
    table at ``market_regions.india.options_grammar.OPTION_GRAMMAR``."""
    from market_regions.india.options_grammar import OPTION_GRAMMAR
    from market_regions.india.plugin import IndiaRegionPlugin

    plugin = IndiaRegionPlugin()
    snapshot = dict(OPTION_GRAMMAR["right_codes"])
    grammar = plugin.options_grammar()
    grammar["right_codes"]["XX"] = "MUTATED"
    grammar["lot_sizes"]["BANGER"] = 999
    assert OPTION_GRAMMAR["right_codes"] == snapshot
    assert "BANGER" not in OPTION_GRAMMAR["lot_sizes"]
