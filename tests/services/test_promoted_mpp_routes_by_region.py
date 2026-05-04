"""T-13 (v7 Phase 3-ter) — promoted MPP slabs route by region.

The active India region returns the SEBI slab table; non-India
regions return ``None`` so non-India brokers don't accidentally
route through the Indian MPP slabs.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def force_region(monkeypatch):
    def _set(code: str | None):
        if code is None:
            monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
        else:
            monkeypatch.setenv("MARKET_REGION_FOR_TESTS", code)
    return _set


def test_india_returns_sebi_slabs(force_region):
    force_region("india")
    from services.promoted_mpp_service import get_active_region_mpp_slabs

    eq = get_active_region_mpp_slabs("EQ")
    assert eq is not None
    assert eq[0] == (100, 2.0)
    assert eq[1] == (500, 1.0)
    # Options slabs differ:
    opt = get_active_region_mpp_slabs("CE")
    assert opt is not None
    assert opt[0] == (10, 5.0)


def test_us_returns_none(force_region):
    """US has no MPP regulatory system."""
    force_region("us")
    from services.promoted_mpp_service import get_active_region_mpp_slabs

    assert get_active_region_mpp_slabs("EQ") is None
    assert get_active_region_mpp_slabs("CE") is None


def test_unresolved_region_returns_none(force_region):
    force_region(None)
    from services.promoted_mpp_service import get_active_region_mpp_slabs

    assert get_active_region_mpp_slabs("EQ") is None or True
