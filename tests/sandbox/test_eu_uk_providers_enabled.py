"""T-21 + T-22 (v7 Phase 6) — EU/UK sandbox providers enabled.

The EU/UK region plugins flip ``feature_flags.sandbox_enabled = true``
so the dispatcher routes sandbox calls to the EU/UK providers
instead of returning ``feature_unsupported``. The provider stubs
(EUSandboxProvider / UKSandboxProvider) declare T+2 settlement,
EUR/GBP base currencies, and EU/UK regular sessions — sufficient
for framework-readiness; production-grade per-venue calendars
remain a future expansion.
"""

from __future__ import annotations


def test_eu_sandbox_enabled():
    from utils.region_loader import load_market_regions

    load_market_regions()
    from utils.region_loader import get_market_region

    eu = get_market_region("eu")
    assert eu is not None
    assert eu.is_feature_enabled("sandbox_enabled") is True


def test_uk_sandbox_enabled():
    from utils.region_loader import load_market_regions

    load_market_regions()
    from utils.region_loader import get_market_region

    uk = get_market_region("uk")
    assert uk is not None
    assert uk.is_feature_enabled("sandbox_enabled") is True


def test_eu_sandbox_provider_declares_eur_t2():
    from services.sandbox.providers.eu import EUSandboxProvider

    p = EUSandboxProvider()
    assert p.base_currency() == "EUR"
    rules = p.position_lifecycle_rules()
    assert rules.settlement_days_equity == 2  # T+2 EU equities


def test_uk_sandbox_provider_declares_gbp_t2():
    from services.sandbox.providers.uk import UKSandboxProvider

    p = UKSandboxProvider()
    assert p.base_currency() == "GBP"
    rules = p.position_lifecycle_rules()
    assert rules.settlement_days_equity == 2  # T+2 UK (post-2024 migration)
