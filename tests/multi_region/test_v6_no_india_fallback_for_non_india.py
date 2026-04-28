"""Phase 3 v6 — no India fallback for non-India regions.

Explicit negative test: for each of `us`, `eu`, `uk` the dispatched
provider's metadata must NOT contain India-shaped strings unless the
caller explicitly named that India venue.

This is the v6 closing invariant `v6-5` precursor — a regression in
this test indicates the dispatcher silently fell back to India.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

INDIA_LITERALS = (
    "Asia/Kolkata", "IST", "INR", "₹",
    "NSE", "NFO", "BSE", "BFO", "MCX", "CDS", "BCD",
    "MIS", "CNC", "NRML",
    "CE", "PE",
    "NIFTY", "BANKNIFTY", "SENSEX", "BANKEX",
    "DDMMMYY",
)

NON_INDIA_REGIONS = ("us", "eu", "uk")


@pytest.mark.parametrize("region_code", NON_INDIA_REGIONS)
def test_sandbox_provider_has_no_india_literals(region_code: str) -> None:
    """The non-India sandbox provider's declared metadata must not
    contain any India-literal string. Provider methods that return
    India values silently are a v6-5 regression."""
    from services.sandbox.dispatcher import get_sandbox_provider

    provider = get_sandbox_provider(region_code)

    # base_currency must not be INR
    currency = provider.base_currency()
    assert currency != "INR", (
        f"{region_code} sandbox provider returned INR as base currency"
    )
    # supported_products must not be the India product set
    products = provider.supported_products()
    india_products = {"MIS", "CNC", "NRML"}
    overlap = products & india_products
    assert not overlap, (
        f"{region_code} sandbox provider returned India products: {overlap}"
    )
    # initial_funds must not equal the India default
    funds = provider.initial_funds()
    assert funds != Decimal("1000000.00"), (
        f"{region_code} sandbox provider returned the India ₹10L default"
    )


@pytest.mark.parametrize("region_code", NON_INDIA_REGIONS)
def test_options_provider_does_not_advertise_india_strategies(region_code: str) -> None:
    """The non-India options provider's supported_strategies set must
    not exactly match the India provider's strategies (the India
    provider declares specific Indian-context strategies; non-India
    providers either declare different sets or empty)."""
    from services.options.dispatcher import get_options_provider

    india = get_options_provider("india")
    other = get_options_provider(region_code)

    # The provider's region_code must not say "india".
    assert other.region_code != "india", (
        f"{region_code} options provider misidentifies its region as india"
    )
    # If the other provider returns a non-empty strategy set, it
    # cannot be identical to India's (India has weekly Thursday
    # weekly strategies that are India-specific).
    other_strategies = other.supported_strategies()
    if other_strategies:
        assert other_strategies != india.supported_strategies(), (
            f"{region_code} options provider declares the same strategy set as India"
        )


@pytest.mark.parametrize("region_code", NON_INDIA_REGIONS)
def test_region_plugin_does_not_carry_india_currency_or_tz(region_code: str) -> None:
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    data = json.loads(
        (repo / "market_regions" / region_code / "plugin.json").read_text(encoding="utf-8")
    )
    assert data["default_currency"] != "INR"
    assert data["timezone_name"] != "Asia/Kolkata"
    # The region's default venue list must not contain Indian venues.
    india_venues = {"NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX"}
    for v in data.get("default_venue_codes", []):
        assert v.upper() not in india_venues, (
            f"{region_code} region plugin declares Indian venue {v!r}"
        )


def test_chartink_remains_india_only() -> None:
    """The Chartink screener provider is intentionally India-only per
    ADR 0028. This test pins that no non-India region was wired into
    Chartink — non-India regions must use a different screener (none
    ships in v6)."""
    from services.screeners.dispatcher import get_screener_provider

    provider = get_screener_provider("chartink")
    assert provider.region_code.lower() == "india", (
        "Chartink provider region must remain india-only per ADR 0028"
    )
