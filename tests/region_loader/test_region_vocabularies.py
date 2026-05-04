"""T-12 (v7 Phase 3-ter) — region plugins declare valid vocabularies.

Each region's plugin.json declares ``product_vocabulary``,
``price_type_vocabulary``, and ``legacy_compat_shim.valid_exchanges``
so promoted-lane callers can read these from
``services.market_region_service`` instead of importing from
``utils.constants`` (the legacy India compat shim).
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _load_regions():
    from utils.region_loader import load_market_regions

    load_market_regions()


def _shim(region):
    shim = region.legacy_compat_shim
    return shim if isinstance(shim, dict) else (
        shim.model_dump() if shim else {}
    )


def test_india_vocabularies():
    from utils.region_loader import get_market_region

    india = get_market_region("india")
    assert india is not None
    shim = _shim(india)
    venues = shim.get("valid_exchanges", [])
    assert {"NSE", "BSE", "NFO", "BFO"}.issubset(set(venues))
    products = (india.product_vocabulary or {}).get("ALL", [])
    assert {"CNC", "NRML", "MIS"}.issubset(set(products))


def test_us_vocabularies():
    from utils.region_loader import get_market_region

    us = get_market_region("us")
    assert us is not None
    shim = _shim(us)
    venues = shim.get("valid_exchanges", [])
    assert "XNYS" in venues
    assert "XNAS" in venues
    products = (us.product_vocabulary or {}).get("ALL", [])
    assert "DAY" in products


def test_eu_vocabularies_minimal():
    from utils.region_loader import get_market_region

    eu = get_market_region("eu")
    assert eu is not None
    shim = _shim(eu)
    venues = shim.get("valid_exchanges", [])
    assert "XPAR" in venues
    assert "XETR" in venues


def test_uk_vocabularies_minimal():
    from utils.region_loader import get_market_region

    uk = get_market_region("uk")
    assert uk is not None
    shim = _shim(uk)
    venues = shim.get("valid_exchanges", [])
    assert venues == ["XLON"]


def test_crypto_vocabularies():
    from utils.region_loader import get_market_region

    crypto = get_market_region("crypto")
    assert crypto is not None
    shim = _shim(crypto)
    assert shim.get("valid_exchanges") == ["CRYPTO"]
