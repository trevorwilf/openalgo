"""T-30 Phase 8 follow-up — Delta Exchange routes through crypto region.

Asserts Delta Exchange's plugin.json declares
``supported_regions: ["crypto"]`` post-T-30. Pre-flip it was
``["india"]`` because crypto was India-region-shaped historically.
The dispatcher now resolves Delta sessions to the crypto region
plugin instead of falling through India's legacy path.
"""

from __future__ import annotations


def test_deltaexchange_supported_regions_is_crypto():
    from utils.plugin_loader import load_broker_capabilities, get_broker_capabilities

    load_broker_capabilities()
    caps = get_broker_capabilities("deltaexchange")
    assert caps is not None, "deltaexchange plugin failed to load"
    assert caps.supported_regions == ["crypto"], (
        f"Delta Exchange should route through crypto region, got "
        f"supported_regions={caps.supported_regions}"
    )


def test_deltaexchange_declares_required_metadata():
    """Per the strict-mode loader (ADR 0025), non-legacy plugins
    must declare market_families, default_currency, base_currency,
    and master_contract_refresh_policy explicitly. Delta now does."""
    from utils.plugin_loader import load_broker_capabilities, get_broker_capabilities

    load_broker_capabilities()
    caps = get_broker_capabilities("deltaexchange")
    assert caps is not None
    assert caps.market_families  # non-empty
    assert caps.base_currency == "USDT"
    assert caps.master_contract_refresh_policy is not None
    assert caps.default_venue_code == "CRYPTO"
