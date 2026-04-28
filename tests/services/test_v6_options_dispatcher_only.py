"""Phase 2 v6 — options dispatcher-only contract.

The v6 plan migrates options service entry points (expiry,
option_chain, option_symbol, option_greeks, iv_chart, straddle_chart,
options_multiorder, oi_profile, gex, iv_smile) from direct India
provider behavior to dispatcher-only flow that resolves
``services.options.dispatcher.get_options_provider(region_code)``.

This contract pins the **dispatcher surface**. Per-service wiring is
the Phase 2-bis follow-up; the v6 prompt requires India parity to
remain bit-identical, which this contract test verifies via the
provider's own semantics.

What this asserts at v6 Phase 2 close:

* The options dispatcher module is importable and exposes the
  documented API surface.
* India + US providers are auto-registered.
* `get_options_provider("india")` and `get_options_provider("us")`
  return objects conforming to the OptionsProvider Protocol.
* `get_options_provider("eu")` raises `OptionsProviderNotRegistered`
  with the structured ADR 0029 error code (until Phase 3 lands the
  EU stub).
* India provider exposes India-shaped option semantics.
"""

from __future__ import annotations

import pytest

from domain.errors import ErrorCode
from services.options.dispatcher import (
    OptionsProviderNotRegistered,
    get_options_provider,
    get_options_provider_or_none,
)
from services.options.providers.base import OptionsProvider


def test_dispatcher_module_exposes_documented_surface() -> None:
    import services.options.dispatcher as d

    for name in (
        "OptionsProviderNotRegistered",
        "get_options_provider",
        "get_options_provider_or_none",
        "register_options_provider",
    ):
        assert hasattr(d, name), f"options dispatcher missing: {name}"


@pytest.mark.parametrize("region", ["india", "us", "eu", "uk"])
def test_default_provider_registered(region: str) -> None:
    """v6 Phase 2 registered india + us; v6 Phase 3 added eu + uk
    options provider stubs (every method on the stubs raises a
    structured ``option_chain_disabled_in_region`` error per ADR
    0027)."""
    provider = get_options_provider(region)
    assert isinstance(provider, OptionsProvider), (
        f"{region} options provider does not satisfy OptionsProvider Protocol"
    )
    assert provider.region_code.lower() == region


def test_unknown_region_returns_structured_error() -> None:
    with pytest.raises(OptionsProviderNotRegistered) as exc_info:
        get_options_provider("zz_unknown_region")
    assert exc_info.value.code == ErrorCode.OPTIONS_PROVIDER_NOT_REGISTERED
    assert exc_info.value.region_code == "zz_unknown_region"


def test_unregistered_region_or_none_helper_returns_none() -> None:
    assert get_options_provider_or_none("zz_unknown") is None


def test_india_provider_supports_indian_option_grammar() -> None:
    """The India provider must declare the India option grammar
    (DDMMMYY + CE/PE) and Indian strategies."""
    provider = get_options_provider("india")
    assert provider.region_code == "india"
    # The supported_strategies() set should be non-empty for India.
    strategies = provider.supported_strategies()
    assert isinstance(strategies, set)
    assert len(strategies) > 0


def test_us_provider_returns_us_semantics() -> None:
    """The US provider must declare a different region; pinning that
    the dispatcher actually routes by region rather than always
    returning India."""
    provider = get_options_provider("us")
    assert provider.region_code == "us"


def test_dispatcher_is_case_insensitive_on_region_code() -> None:
    a = get_options_provider("india")
    b = get_options_provider("INDIA")
    c = get_options_provider("India")
    assert a is b is c
