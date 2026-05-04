"""T-30 (v7 Phase 8) — crypto region plugin loads.

Verifies the new ``market_regions/crypto/`` plugin satisfies the
schema and contributes to the now-five-region matrix
(india / us / eu / uk / crypto).

Per the prompt's Option A decision:
* No country_codes (crypto is borderless).
* 24/7 sessions (ALL_DAY).
* USDT as the default quote currency.
* Delta Exchange's ``supported_regions`` flip is deferred to a
  follow-up commit (parity-sensitive).
"""

from __future__ import annotations

import pytest


def test_crypto_region_loads_in_matrix():
    from utils.region_loader import load_market_regions, get_market_region

    regions = load_market_regions()
    assert "crypto" in regions
    assert {"india", "us", "eu", "uk", "crypto"}.issubset(set(regions.keys()))


def test_crypto_region_metadata():
    from utils.region_loader import get_market_region

    crypto = get_market_region("crypto")
    assert crypto is not None
    assert crypto.timezone_name == "UTC"
    assert crypto.default_currency == "USDT"
    # No country mapping per Option A.
    assert list(crypto.country_codes) == []
    # The single CRYPTO venue is registered.
    venues = [v.venue_code for v in crypto.venues]
    assert venues == ["CRYPTO"]


def test_crypto_region_24x7_session():
    """Crypto sessions are continuous (ALL_DAY in the v2 session
    enum). At least one session template must mark all 7 days."""
    from utils.region_loader import get_market_region

    crypto = get_market_region("crypto")
    assert crypto is not None
    sessions = list(crypto.session_templates)
    assert sessions, "crypto region declared no session templates"
    # The first session must include all 7 days_of_week.
    assert sorted(sessions[0].days_of_week) == [0, 1, 2, 3, 4, 5, 6]


def test_india_no_longer_declares_crypto():
    """T-30 (v7 Phase 8 final): India relinquished CRYPTO when
    Delta Exchange flipped to ``supported_regions: ["crypto"]``.
    India's ``legacy_compat_shim.valid_exchanges`` no longer
    includes ``"CRYPTO"`` — Delta Exchange routes through the
    crypto region instead. The 3 affected parity baselines
    (parity_quote, parity_history, parity_place_order_validation)
    were regenerated to drop ``CRYPTO`` from their valid-exchange
    error string."""
    from utils.region_loader import get_market_region

    india = get_market_region("india")
    assert india is not None
    shim = india.legacy_compat_shim
    valid = shim["valid_exchanges"] if isinstance(shim, dict) else shim.valid_exchanges
    assert "CRYPTO" not in valid, (
        "T-30 carve-out: India should no longer claim CRYPTO. "
        "Delta Exchange handles crypto via the crypto region plugin."
    )


def test_crypto_region_owns_crypto_exchange():
    """The crypto region declares ``CRYPTO`` as its sole valid
    exchange post-T-30."""
    from utils.region_loader import get_market_region

    crypto = get_market_region("crypto")
    assert crypto is not None
    shim = crypto.legacy_compat_shim
    valid = shim["valid_exchanges"] if isinstance(shim, dict) else shim.valid_exchanges
    assert "CRYPTO" in valid
