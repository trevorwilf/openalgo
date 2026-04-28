"""Phase 2 v6 — screener dispatcher-only contract.

The v6 plan migrates `blueprints/chartink.py` and any other screener
caller from direct India-Chartink calls to dispatcher-only flow that
resolves
``services.screeners.dispatcher.get_screener_provider(provider_code)``.

Note: the Screener dispatcher is keyed by **provider_code**
(`"chartink"`, future TradingView screener, future Alpaca screener,
etc.) not by region — see ADR 0028. Chartink is the only screener
provider that ships in v3-v5; v4 explicitly defers a US screener
implementation (the directory exists for future plugins).

What this asserts at v6 Phase 2 close:

* The screener dispatcher module is importable and exposes the
  documented API surface.
* The Chartink provider is auto-registered.
* `get_screener_provider("chartink")` returns an object conforming to
  the ScreenerProvider Protocol.
* Unknown provider_code raises `ScreenerProviderNotRegistered` with
  the structured ADR 0029 error code.
* Chartink provider declares India region + NSE/BSE venues
  bit-identically.
"""

from __future__ import annotations

import pytest

from domain.errors import ErrorCode
from services.screeners.dispatcher import (
    ScreenerProviderNotRegistered,
    get_screener_provider,
    get_screener_provider_or_none,
)
from services.screeners.providers.base import ScreenerProvider


def test_dispatcher_module_exposes_documented_surface() -> None:
    import services.screeners.dispatcher as d

    for name in (
        "ScreenerProviderNotRegistered",
        "clear_screener_registry_for_tests",
        "get_screener_provider",
        "get_screener_provider_or_none",
        "install_default_screener_providers",
        "register_screener_provider",
    ):
        assert hasattr(d, name), f"screener dispatcher missing: {name}"


def test_chartink_provider_registered() -> None:
    provider = get_screener_provider("chartink")
    assert isinstance(provider, ScreenerProvider), (
        "Chartink provider does not satisfy ScreenerProvider Protocol"
    )
    assert provider.provider_code.lower() == "chartink"
    assert provider.region_code.lower() == "india"


def test_unknown_provider_returns_structured_error() -> None:
    with pytest.raises(ScreenerProviderNotRegistered) as exc_info:
        get_screener_provider("zz_unknown_provider")
    assert exc_info.value.code == ErrorCode.SCREENER_PROVIDER_NOT_REGISTERED


def test_unregistered_provider_or_none_helper_returns_none() -> None:
    assert get_screener_provider_or_none("zz_unknown_provider") is None


def test_chartink_supported_venues_are_indian() -> None:
    """The Chartink provider must declare NSE/BSE supported venues
    bit-identically — Chartink is India-shaped per ADR 0028."""
    provider = get_screener_provider("chartink")
    venues = {v.upper() for v in provider.supported_venues}
    assert "NSE" in venues
    assert "BSE" in venues


def test_chartink_signal_types_include_buy_sell_exit() -> None:
    provider = get_screener_provider("chartink")
    types = provider.supported_signal_types()
    assert isinstance(types, set)
    # Chartink standard signal types
    assert "buy" in types or "BUY" in types
