"""Phase 1 v5 (ADR 0029) — structured market-context error taxonomy.

Each new v5 error code (and the extended `unsupported_capability`
dimension) round-trips through its dedicated exception class. Test
asserts every code is reachable via the exception class, that the
`code` attribute matches `ErrorCode`, and that constructor enforces
constraints on `dimension` / `feature` enums.
"""

from __future__ import annotations

import pytest

from domain.errors import (
    EntitlementRequired,
    ErrorCode,
    LegacyLaneBlocked,
    MissingCurrencyContext,
    MissingInstrumentIdentity,
    MissingRegionContext,
    MissingTranslator,
    MissingVenueContext,
    UnsupportedCapability,
    UnsupportedProvider,
    UnsupportedRegion,
    UnsupportedVenue,
)


def test_unsupported_region_carries_code_and_region():
    err = UnsupportedRegion("eu")
    assert err.code == ErrorCode.UNSUPPORTED_REGION == "unsupported_region"
    assert err.region_code == "eu"


def test_missing_region_context_records_attempted_sources():
    err = MissingRegionContext(attempted_sources=["broker_capability", "stored_default"])
    assert err.code == ErrorCode.MISSING_REGION_CONTEXT == "missing_region_context"
    assert err.attempted_sources == ["broker_capability", "stored_default"]


def test_unsupported_venue_carries_code_and_venue():
    err = UnsupportedVenue("XHKG")
    assert err.code == ErrorCode.UNSUPPORTED_VENUE == "unsupported_venue"
    assert err.venue_code == "XHKG"


def test_missing_venue_context_carries_code():
    err = MissingVenueContext()
    assert err.code == ErrorCode.MISSING_VENUE_CONTEXT == "missing_venue_context"


def test_unsupported_capability_dimension_extension():
    err = UnsupportedCapability("_mock_x", "tif", details="GTC", dimension="tif")
    assert err.dimension == "tif"
    assert "tif" in str(err)


def test_unsupported_capability_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        UnsupportedCapability("_mock_x", "tif", dimension="not_a_dim")


def test_unsupported_capability_dimension_set_is_canonical():
    expected = {
        "order_type",
        "tif",
        "session",
        "quantity_unit",
        "currency",
        "asset_class",
        "product_intent",
        "combo_type",
        "stream_transport",
    }
    assert set(UnsupportedCapability.DIMENSIONS) == expected


def test_missing_currency_context_carries_code():
    err = MissingCurrencyContext()
    assert err.code == ErrorCode.MISSING_CURRENCY_CONTEXT == "missing_currency_context"


def test_missing_instrument_identity_carries_code():
    err = MissingInstrumentIdentity()
    assert err.code == ErrorCode.MISSING_INSTRUMENT_IDENTITY == "missing_instrument_identity"


def test_missing_translator_carries_code_and_broker():
    err = MissingTranslator("_mock_xyz")
    assert err.code == ErrorCode.MISSING_TRANSLATOR == "missing_translator"
    assert err.broker_code == "_mock_xyz"


def test_unsupported_provider_carries_feature_and_region():
    err = UnsupportedProvider("sandbox", region_code="eu")
    assert err.code == ErrorCode.UNSUPPORTED_PROVIDER == "unsupported_provider"
    assert err.feature == "sandbox"
    assert err.region_code == "eu"


def test_unsupported_provider_rejects_unknown_feature():
    with pytest.raises(ValueError):
        UnsupportedProvider("not_a_feature")


def test_unsupported_provider_feature_set_is_canonical():
    expected = {
        "sandbox",
        "options",
        "screener",
        "analyzer",
        "flow",
        "iv",
        "gex",
        "straddle",
        "synthetic_future",
        "oi",
    }
    assert set(UnsupportedProvider.FEATURES) == expected


def test_legacy_lane_blocked_carries_surface():
    err = LegacyLaneBlocked("place_order_service", broker_code="_mock_schwab_like")
    assert err.code == ErrorCode.LEGACY_LANE_BLOCKED == "legacy_lane_blocked"
    assert err.surface == "place_order_service"
    assert err.broker_code == "_mock_schwab_like"


def test_entitlement_required_carries_entitlement():
    err = EntitlementRequired("options_level_2", account_id="abc-123")
    assert err.code == ErrorCode.ENTITLEMENT_REQUIRED == "entitlement_required"
    assert err.entitlement == "options_level_2"
    assert err.account_id == "abc-123"


def test_v5_error_codes_distinct_strings():
    """Every v5 code should be a unique string and not collide with existing codes."""
    new_codes = {
        ErrorCode.UNSUPPORTED_REGION,
        ErrorCode.MISSING_REGION_CONTEXT,
        ErrorCode.UNSUPPORTED_VENUE,
        ErrorCode.MISSING_VENUE_CONTEXT,
        ErrorCode.MISSING_CURRENCY_CONTEXT,
        ErrorCode.MISSING_INSTRUMENT_IDENTITY,
        ErrorCode.MISSING_TRANSLATOR,
        ErrorCode.UNSUPPORTED_PROVIDER,
        ErrorCode.LEGACY_LANE_BLOCKED,
        ErrorCode.ENTITLEMENT_REQUIRED,
    }
    # All distinct string values.
    assert len(new_codes) == 10

    # No collision with any pre-existing error code.
    pre_existing = {
        v
        for k, v in ErrorCode.__dict__.items()
        if not k.startswith("_") and isinstance(v, str) and v not in new_codes
    }
    assert new_codes.isdisjoint(pre_existing)
