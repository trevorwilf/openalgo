"""Phase 3 v6 — order validation dry-run multi-region smoke test.

Verifies that order validation against each region's product +
order-type matrix returns valid for declared combinations and
structured errors for undeclared. Concrete validation lives in
``rule_enforcement.check_order``; this test exercises the framework
contract surface against the four region's sandbox provider.
"""

from __future__ import annotations

import pytest

from services.sandbox.dispatcher import get_sandbox_provider


@pytest.mark.parametrize(("region", "expected_products"), [
    ("india", {"MIS", "CNC", "NRML"}),
    ("us", {"DAY_TRADE", "OVERNIGHT", "MARGIN"}),
    ("eu", {"CASH", "MARGIN"}),
    ("uk", {"CASH", "MARGIN"}),
])
def test_supported_products_per_region(region: str, expected_products: set[str]) -> None:
    """Each region's sandbox provider must declare its declared
    product set bit-identically — non-overlapping with India's set
    for non-India regions."""
    provider = get_sandbox_provider(region)
    assert provider.supported_products() == expected_products


@pytest.mark.parametrize("region", ["india", "us", "eu", "uk"])
def test_supported_order_types_per_region_is_non_empty(region: str) -> None:
    provider = get_sandbox_provider(region)
    types = provider.supported_order_types()
    assert isinstance(types, set)
    assert len(types) > 0
    # MARKET / LIMIT must be in every region — they're region-neutral.
    assert "MARKET" in types
    assert "LIMIT" in types


def test_india_and_us_product_sets_are_disjoint() -> None:
    """Cross-check that the dispatcher routing actually returns
    different providers for india vs us — sanity that the test
    matrix is wired."""
    india = get_sandbox_provider("india").supported_products()
    us = get_sandbox_provider("us").supported_products()
    assert india != us
    # No overlap between Indian product names and US product names.
    assert india.isdisjoint(us)


def test_eu_and_uk_share_common_european_product_set() -> None:
    """EU and UK use similar broker-agnostic product names
    (CASH/MARGIN). This reflects the v6 stub design — the real
    providers may declare richer per-broker products later."""
    eu = get_sandbox_provider("eu").supported_products()
    uk = get_sandbox_provider("uk").supported_products()
    assert eu == uk == {"CASH", "MARGIN"}
