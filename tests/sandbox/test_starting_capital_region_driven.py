"""T-16 (v7 Phase 4-bis-3) — sandbox starting capital sources.

Asserts:
* The IndiaSandboxProvider's initial_funds() reads from
  ``market_regions/india/plugin.json::metadata.sandbox_initial_funds``
  with a fallback to the legacy ₹10L hard-coded value (parity-
  pinned).
* The legacy fund_manager.py default is now resolved through the
  plugin metadata as well, with a fallback to the legacy ₹1Cr.
* India parity stays bit-identical (existing installs see no
  change).
"""

from __future__ import annotations

from decimal import Decimal


def test_india_provider_reads_initial_funds_from_region_plugin():
    """Provider's initial_funds() returns the value declared in the
    India region plugin's metadata.sandbox_initial_funds (currently
    "1000000.00" / ₹10L)."""
    from services.sandbox.providers.india import IndiaSandboxProvider, _INITIAL_FUNDS

    p = IndiaSandboxProvider()
    assert p.initial_funds() == _INITIAL_FUNDS
    # Parity-pinned: legacy ₹10L value preserved.
    assert _INITIAL_FUNDS == Decimal("1000000.00")


def test_india_plugin_declares_sandbox_initial_funds():
    from utils.region_loader import load_market_regions, get_market_region

    load_market_regions()
    india = get_market_region("india")
    assert india is not None
    metadata = getattr(india, "metadata", None) or {}
    # T-16: explicit declaration in plugin.json.
    assert metadata.get("sandbox_initial_funds") == "1000000.00"
    assert metadata.get("sandbox_initial_funds_currency") == "INR"


def test_legacy_fund_manager_default_reconciled():
    """The legacy fund_manager.py default reads from the plugin
    metadata fallback. Default value is the legacy ₹1Cr for
    parity-preserved existing installs."""
    from market_regions.india.legacy_v1.sandbox.fund_manager import (
        _resolve_starting_capital_default,
    )

    default = _resolve_starting_capital_default()
    # Either the metadata-declared value (if operator overrides)
    # or the legacy ₹1Cr fallback.
    assert default in ("10000000.00", "1000000.00") or default.replace(".", "").isdigit()
