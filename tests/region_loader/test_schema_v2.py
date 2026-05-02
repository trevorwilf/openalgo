"""Phase 2 — region plugin schema v2 loader behavior.

* v1 plugins continue to validate verbatim.
* v2 plugins (any of venues / session_templates / calendar_exceptions /
  symbol_display / feature_flags present) validate against the v2
  schema.
* Malformed v2 sub-objects produce clear error messages and the broker
  is skipped, not crashed.
* The shipped india/us/uk/eu plugins all validate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.regions import MarketRegion
from utils import region_loader


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset(reset_loader_state):
    yield


def _v1_payload() -> dict:
    return {
        "region_code": "v1demo",
        "display_name": "V1 demo",
        "timezone_name": "UTC",
        "market_families": ["OTHER"],
    }


def _v2_payload() -> dict:
    p = _v1_payload()
    p["region_code"] = "v2demo"
    p["display_name"] = "V2 demo"
    p["venues"] = [
        {
            "venue_code": "DEMO",
            "display_name": "Demo Venue",
            "country_code": "US",
            "timezone_name": "America/New_York",
            "base_currency": "USD",
            "market_family": "US_STOCK",
            "settlement_template": "T+1",
            "session_model": "REGULAR_ONLY",
        }
    ]
    p["session_templates"] = [
        {
            "session_code": "REGULAR",
            "venue_codes": ["DEMO"],
            "local_start_time": "09:30",
            "local_end_time": "16:00",
            "days_of_week": [0, 1, 2, 3, 4],
        }
    ]
    p["symbol_display"] = {
        "date_format": "YYYY-MM-DD",
        "option_right_codes": ["CALL", "PUT"],
    }
    p["feature_flags"] = {"option_chain_enabled": False}
    return p


def test_detect_schema_version_v1() -> None:
    assert region_loader.detect_schema_version(_v1_payload()) == "v1"


def test_detect_schema_version_v2() -> None:
    assert region_loader.detect_schema_version(_v2_payload()) == "v2"


def test_v1_plugin_still_validates(make_region_tree, chdir) -> None:
    make_region_tree({"v1demo": _v1_payload()})
    regions = region_loader.load_market_regions("market_regions")
    assert "v1demo" in regions
    assert regions["v1demo"].venues == []
    assert regions["v1demo"].symbol_display.date_format is None


def test_v2_plugin_validates_and_loads(make_region_tree, chdir) -> None:
    make_region_tree({"v2demo": _v2_payload()})
    regions = region_loader.load_market_regions("market_regions")
    assert "v2demo" in regions
    region = regions["v2demo"]
    assert len(region.venues) == 1
    assert region.venues[0].venue_code == "DEMO"
    assert region.session_templates[0].venue_codes == ["DEMO"]
    assert region.symbol_display.date_format == "YYYY-MM-DD"
    assert region.is_feature_enabled("option_chain_enabled") is False


def test_v2_malformed_venue_skipped_with_log(
    make_region_tree, chdir, caplog
) -> None:
    bad = _v2_payload()
    bad["venues"][0].pop("venue_code")  # required
    make_region_tree({"v2bad": bad})
    with caplog.at_level("ERROR"):
        regions = region_loader.load_market_regions("market_regions")
    assert "v2bad" not in regions
    assert any("schema validation" in rec.message for rec in caplog.records)


def test_v2_malformed_session_template_skipped(make_region_tree, chdir) -> None:
    bad = _v2_payload()
    bad["session_templates"][0]["local_start_time"] = "9-30"  # bad pattern
    make_region_tree({"v2bad": bad})
    regions = region_loader.load_market_regions("market_regions")
    assert "v2bad" not in regions


def test_v2_calendar_exception_unknown_type_rejected(
    make_region_tree, chdir
) -> None:
    bad = _v2_payload()
    bad["calendar_exceptions"] = [
        {
            "date": "2026-01-01",
            "venue_code": "DEMO",
            "exception_type": "PARTY",  # not in enum
        }
    ]
    make_region_tree({"v2bad": bad})
    regions = region_loader.load_market_regions("market_regions")
    assert "v2bad" not in regions


def test_shipped_india_plugin_validates_v2(chdir) -> None:
    """Real india plugin loads via the v2 schema."""
    payload = json.loads(
        (REPO_ROOT / "market_regions" / "india" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert region_loader.detect_schema_version(payload) == "v2"
    region = MarketRegion(**payload)
    assert region.region_code == "india"
    # Phase 3 (T-20) — venue catalog expanded to include the full
    # legacy VALID_EXCHANGES set so the region's venues field can
    # back the promoted-lane venue allow-list. CRYPTO is intentionally
    # NOT a venue (it's a broker-side classifier carried by
    # ``legacy_compat_shim.valid_exchanges``).
    assert {v.venue_code for v in region.venues} == {
        "NSE",
        "BSE",
        "NFO",
        "BFO",
        "CDS",
        "BCD",
        "MCX",
        "NCDEX",
        "NSE_INDEX",
        "BSE_INDEX",
    }
    assert region.symbol_display.date_format == "DDMMMYY"
    assert region.is_feature_enabled("option_chain_enabled") is True
    # Phase 3 (T-20) — vocabulary fields populated so the migrated
    # service helpers can consume them.
    assert region.product_vocabulary.get("ALL") == ["CNC", "NRML", "MIS"]
    assert region.price_type_vocabulary.get("ALL") == ["MARKET", "LIMIT", "SL", "SL-M"]
    assert "CRYPTO" in (region.legacy_compat_shim or {}).get("valid_exchanges", [])


def test_shipped_us_plugin_validates_v2() -> None:
    payload = json.loads(
        (REPO_ROOT / "market_regions" / "us" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert region_loader.detect_schema_version(payload) == "v2"
    region = MarketRegion(**payload)
    venue = region.get_venue("XNYS")
    assert venue is not None
    assert venue.timezone_name == "America/New_York"


def test_shipped_uk_plugin_validates_v2() -> None:
    payload = json.loads(
        (REPO_ROOT / "market_regions" / "uk" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    region = MarketRegion(**payload)
    sessions = region.get_sessions_for("XLON")
    assert sessions and sessions[0].session_code.value == "REGULAR"


def test_shipped_eu_plugin_validates_v2() -> None:
    payload = json.loads(
        (REPO_ROOT / "market_regions" / "eu" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    region = MarketRegion(**payload)
    assert {v.venue_code for v in region.venues} == {"XPAR", "XETR"}
