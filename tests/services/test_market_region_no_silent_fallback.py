"""Phase 2 v4 — services.market_region_service no-silent-fallback tests.

Confirms the FALLBACK_REGION_CODE constant has been removed and the
named replacement helper still picks India when the region catalog
contains it (preserving backward-compat for installations that have
not configured a default).
"""

from __future__ import annotations

import pytest

from services import market_region_service


def test_no_module_level_fallback_region_code_constant() -> None:
    assert not hasattr(market_region_service, "FALLBACK_REGION_CODE"), (
        "services.market_region_service.FALLBACK_REGION_CODE must not "
        "exist after v4 Phase 2 (ADR 0023 invariant 1)."
    )


def test_legacy_india_helper_returns_india() -> None:
    assert market_region_service._legacy_india_region_for_compat() == "india"


def test_fallback_region_code_prefers_india_when_present() -> None:
    catalog = {"india": object(), "us": object()}
    assert market_region_service._fallback_region_code(catalog) == "india"


def test_fallback_region_code_picks_first_when_no_india() -> None:
    catalog = {"us": object(), "eu": object()}
    # Dict iteration order is insertion order in 3.7+ — first key wins.
    assert market_region_service._fallback_region_code(catalog) == "us"


def test_fallback_region_code_returns_none_for_empty() -> None:
    assert market_region_service._fallback_region_code({}) is None
