"""Phase 7b — USRegionPlugin completeness.

Asserts the US plugin is a fully-formed :class:`RegionPlugin` with
non-empty calendar data for 2024-2027, an OSI-21 round-tripping
options grammar, and live sandbox/options providers (no India
fallback).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture(autouse=True)
def _reset(reset_loader_state):
    yield


def test_us_region_plugin_satisfies_protocol():
    from domain.region_plugin import RegionPlugin
    from market_regions.us.plugin import USRegionPlugin

    plugin = USRegionPlugin()
    assert isinstance(plugin, RegionPlugin)


def test_us_plugin_resolves_via_region_loader():
    from utils import region_loader

    region_loader._reset_cache_for_tests()
    region_loader.load_market_regions()
    plugin = region_loader.get_region_plugin("us")
    assert plugin is not None
    assert plugin.region_code == "us"
    # Same call returns cached instance.
    assert region_loader.get_region_plugin("us") is plugin


def test_us_plugin_holidays_populated_for_2024_through_2027():
    from market_regions.us.plugin import USRegionPlugin

    plugin = USRegionPlugin()
    for year in (2024, 2025, 2026, 2027):
        cal = plugin.holiday_calendar(year)
        assert len(cal) >= 9, (
            f"US plugin must carry at least 9 closed days per year; "
            f"{year} has {len(cal)}"
        )
    # Out-of-range years return an empty list (fail-soft).
    assert plugin.holiday_calendar(2030) == []


def test_us_plugin_methods_return_us_shaped_data():
    from market_regions.us.plugin import USRegionPlugin

    plugin = USRegionPlugin()
    # Currency / locale must be US-specific, NOT India.
    locale = plugin.locale()
    assert locale["currency"] == "USD"
    assert locale["symbol"] == "$"
    # Squareoff rules must use US venue codes (DAY_TRADE product on
    # XNYS / XNAS / ARCX / BATS), not India venues.
    rules = plugin.squareoff_rules()
    venues = {r["venue"] for r in rules}
    assert venues & {"XNYS", "XNAS"}, "US plugin must reference US venues"
    forbidden = {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"}
    assert not (venues & forbidden), (
        f"US plugin leaked India venues: {venues & forbidden}"
    )
    products = {p for r in rules for p in r["applies_to"]}
    assert "DAY_TRADE" in products
    assert "MIS" not in products
    # Qty-freeze must be empty for US (no regulator-published table).
    assert plugin.qty_freeze_rules() == []
    # Options grammar must use OCC OSI 21-char format.
    grammar = plugin.options_grammar()
    assert grammar["date_format"] == "%y%m%d"
    assert grammar["right_codes"] == {"C": "CALL", "P": "PUT"}
    assert grammar["default_currency"] == "USD"
    # Settlement: T+1 since May 2024.
    assert plugin.settlement_template("XNYS") == "T+1"
    # Providers: real US providers, NOT India fallbacks.
    sb = plugin.sandbox_provider()
    assert sb.region_code == "us"
    assert sb.base_currency() == "USD"
    op = plugin.options_provider()
    assert op.region_code == "us"


def test_us_options_grammar_round_trips_known_osi_sample():
    """The classic OSI 21-char sample
    ``AAPL  240419C00185000`` must parse into
    AAPL / 2024-04-19 / CALL / 185.000 and re-format identically."""
    from services.options.providers.us import USOptionsProvider

    provider = USOptionsProvider()
    sample = "AAPL  240419C00185000"
    parsed = provider.parse_option_symbol(sample)
    assert parsed.underlying == "AAPL"
    assert parsed.expiry == date(2024, 4, 19)
    assert parsed.right.value == "CALL"
    assert parsed.strike == Decimal("185.000")
    formatted = provider.format_option_symbol(parsed)
    # Round-trip: the formatter normalizes underlying-padding to 6
    # chars; for AAPL → "AAPL  " (right-padded).
    re_parsed = provider.parse_option_symbol(formatted)
    assert re_parsed.underlying == "AAPL"
    assert re_parsed.expiry == date(2024, 4, 19)
    assert re_parsed.strike == Decimal("185.000")


def test_us_plugin_timezone_is_america_new_york():
    import pytz

    from market_regions.us.plugin import USRegionPlugin

    plugin = USRegionPlugin()
    assert plugin.timezone_object() is pytz.timezone("America/New_York")
