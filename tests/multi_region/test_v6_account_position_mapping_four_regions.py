"""Phase 3 v6 — account/position mapping multi-region smoke test.

Verifies that the canonical account/position normalization shape
declares an explicit currency, region, and venue per region.
"""

from __future__ import annotations

import pytest

from services.sandbox.dispatcher import get_sandbox_provider


@pytest.mark.parametrize(("region", "expected_currency"), [
    ("india", "INR"),
    ("us", "USD"),
    ("eu", "EUR"),
    ("uk", "GBP"),
])
def test_provider_base_currency_matches_region(region: str, expected_currency: str) -> None:
    """Account / position normalization must report the region's
    base currency. The dispatcher's provider IS the source of
    truth for "what currency does this region transact in?". The
    legacy India fallback is forbidden for non-India regions."""
    provider = get_sandbox_provider(region)
    assert provider.base_currency() == expected_currency


@pytest.mark.parametrize("region", ["india", "us", "eu", "uk"])
def test_provider_initial_funds_is_in_provider_currency(region: str) -> None:
    """The provider's ``initial_funds()`` decimal must be
    interpretable in the provider's base currency. We don't compare
    cross-region magnitudes (different currencies), but each must
    return a non-zero positive amount."""
    from decimal import Decimal

    provider = get_sandbox_provider(region)
    funds = provider.initial_funds()
    assert isinstance(funds, Decimal)
    assert funds > Decimal(0)


@pytest.mark.parametrize("region", ["india", "us", "eu", "uk"])
def test_provider_position_lifecycle_rules_are_complete(region: str) -> None:
    """Every region's lifecycle rules must declare every field
    in the ProviderRules dataclass."""
    from services.sandbox.providers.base import ProviderRules

    provider = get_sandbox_provider(region)
    rules = provider.position_lifecycle_rules()
    assert isinstance(rules, ProviderRules)
    # All fields must be set.
    assert rules.settlement_days_equity >= 0
    assert rules.settlement_days_options >= 0
    assert isinstance(rules.day_trade_close_required, bool)
    assert isinstance(rules.overnight_allowed, bool)
    assert isinstance(rules.partial_fills_supported, bool)


def test_india_settlement_is_t_plus_1_bit_identically() -> None:
    """Pin the India settlement invariant — Phase 2-bis sandbox
    blueprint migration must not change this."""
    rules = get_sandbox_provider("india").position_lifecycle_rules()
    assert rules.settlement_days_equity == 1
    assert rules.settlement_days_options == 1
    assert rules.day_trade_close_required is True
    assert rules.overnight_allowed is True
    assert rules.partial_fills_supported is False


def test_us_settlement_is_t_plus_2_for_equity() -> None:
    """Pin the US settlement invariant — different from India,
    confirms dispatcher routing is doing real work."""
    rules = get_sandbox_provider("us").position_lifecycle_rules()
    assert rules.settlement_days_equity == 2
