"""Phase 0 (T-01) — region plugin schema v3 fields.

Asserts that:
* The 10 new optional fields exist on ``MarketRegion`` with correct
  empty defaults (dict / list / dict / list / dict / dict / dict / dict
  / list / dict).
* All four shipped region manifests (``india``, ``us``, ``eu``, ``uk``)
  still load without modification through the loader.
* Pydantic round-trip is identity for the new fields when populated.

These fields are added in Phase 0 so later phases (2 / 3 / 5 / 6 / 7)
have a place to put the relocated India data without a second schema
migration. No live consumer reads them in Phase 0.
"""

from __future__ import annotations

from typing import Any

import pytest

from domain.regions import MarketRegion
from utils import region_loader


REQUIRED_V3_FIELDS: tuple[tuple[str, type], ...] = (
    ("product_vocabulary", dict),
    ("price_type_vocabulary", dict),
    ("mandatory_close_rules", list),
    ("quantity_freeze_rules", list),
    ("currency_locale", dict),
    ("option_grammar", dict),
    ("index_classification", dict),
    ("legacy_compat_shim", dict),
    ("screener_providers", list),
    ("master_contract_refresh_policy", dict),
)


@pytest.fixture(autouse=True)
def _reset(reset_loader_state):
    yield


def _minimal_region_payload() -> dict[str, Any]:
    return {
        "region_code": "v3demo",
        "display_name": "V3 demo",
        "timezone_name": "UTC",
        "market_families": ["OTHER"],
    }


def test_all_v3_fields_present_on_marketregion_with_correct_defaults() -> None:
    region = MarketRegion(**_minimal_region_payload())
    for name, expected_type in REQUIRED_V3_FIELDS:
        assert hasattr(region, name), f"MarketRegion missing v3 field {name!r}"
        value = getattr(region, name)
        assert isinstance(value, expected_type), (
            f"{name!r} default is {type(value).__name__}, expected {expected_type.__name__}"
        )
        # Defaults must be empty
        assert not value, f"{name!r} default should be empty, got {value!r}"


def test_shipped_manifests_load_with_v3_fields_defaulted() -> None:
    region_loader.load_market_regions()
    codes = region_loader.list_market_regions()
    assert {"india", "us", "eu", "uk"}.issubset(set(codes)), (
        f"Expected india/us/eu/uk among shipped regions, got {codes}"
    )
    for code in ("india", "us", "eu", "uk"):
        region = region_loader.get_market_region(code)
        assert region is not None, f"region {code!r} did not load"
        for name, expected_type in REQUIRED_V3_FIELDS:
            value = getattr(region, name)
            assert isinstance(value, expected_type), (
                f"region {code!r} field {name!r} type drift"
            )


def test_v3_fields_pydantic_round_trip_identity_when_populated() -> None:
    populated = {
        **_minimal_region_payload(),
        "product_vocabulary": {"EQUITY": ["MIS", "CNC"], "FUTURE": ["NRML"]},
        "price_type_vocabulary": {"EQUITY": ["MARKET", "LIMIT", "SL", "SL-M"]},
        "mandatory_close_rules": [
            {"venue": "NSE", "local_close": "15:15", "applies_to": ["MIS"]}
        ],
        "quantity_freeze_rules": [{"venue": "NFO", "underlying": "NIFTY", "qty_freeze": 1800}],
        "currency_locale": {"INR": "en-IN", "USD": "en-US"},
        "option_grammar": {"date_format": "DDMMMYY", "right_codes": ["CE", "PE"]},
        "index_classification": {"NSE": ["NSE_INDEX"], "BSE": ["BSE_INDEX"]},
        "legacy_compat_shim": {"v1_lane_attached": True, "version": "v1"},
        "screener_providers": ["chartink"],
        "master_contract_refresh_policy": {
            "timezone": "Asia/Kolkata",
            "cutoff_local": "08:00",
            "frequency": "daily",
        },
    }
    region = MarketRegion(**populated)
    dumped = region.model_dump()
    rehydrated = MarketRegion(**dumped)
    for name, _ in REQUIRED_V3_FIELDS:
        assert getattr(rehydrated, name) == getattr(region, name), (
            f"v3 field {name!r} did not round-trip"
        )


def test_v3_fields_optional_omission_does_not_error() -> None:
    """A manifest that omits every v3 field still validates."""
    region = MarketRegion(**_minimal_region_payload())
    assert region.product_vocabulary == {}
    assert region.mandatory_close_rules == []
    assert region.master_contract_refresh_policy == {}
