"""Phase 2 v6 — sandbox dispatcher-only contract.

The v6 plan migrates sandbox blueprints from direct India-provider
calls to dispatcher-only flow that resolves
``services.sandbox.dispatcher.get_sandbox_provider(region_code)``
and uses the returned :class:`SandboxProvider` for settlement /
square-off / fill / product semantics.

This contract pins the **dispatcher surface** that the migration
will use. It does NOT yet assert that every blueprint calls the
dispatcher (that wiring is the Phase 2-bis follow-up; introducing
it without per-surface browser verification risks breaking India
parity, which is the gatekeeper per the v6 prompt).

What this test asserts at v6 Phase 2 close:

* The dispatcher module is importable and exposes the documented
  API surface.
* India + US providers are auto-registered at module import.
* `get_sandbox_provider("india")` and `get_sandbox_provider("us")`
  return objects conforming to the SandboxProvider Protocol.
* `get_sandbox_provider("eu")` raises `SandboxProviderNotRegistered`
  with the structured ADR 0029 error code (until Phase 3 ships the
  EU stub).
* Each provider exposes the required Protocol methods returning the
  expected shape (region_code, base_currency, supported_products,
  partial_fills_supported, position_lifecycle_rules).
* India provider returns India semantics bit-identically (T+1
  settlement, MIS/CNC/NRML, INR, ₹10L, no partials).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domain.errors import ErrorCode
from services.sandbox.dispatcher import (
    SandboxProviderNotRegistered,
    get_sandbox_provider,
    get_sandbox_provider_or_none,
)
from services.sandbox.providers.base import ProviderRules, SandboxProvider


def test_dispatcher_module_exposes_documented_surface() -> None:
    import services.sandbox.dispatcher as d

    for name in (
        "SandboxProviderNotRegistered",
        "clear_sandbox_registry_for_tests",
        "get_sandbox_provider",
        "get_sandbox_provider_or_none",
        "install_default_sandbox_providers",
        "register_sandbox_provider",
    ):
        assert hasattr(d, name), f"dispatcher missing public name: {name}"


@pytest.mark.parametrize("region", ["india", "us", "eu", "uk"])
def test_default_provider_registered(region: str) -> None:
    """v6 Phase 2 registered india + us; v6 Phase 3 added eu + uk
    stubs. All four region stubs are now registered."""
    provider = get_sandbox_provider(region)
    assert isinstance(provider, SandboxProvider), (
        f"{region} provider does not satisfy SandboxProvider Protocol"
    )
    assert provider.region_code.lower() == region


def test_unknown_region_returns_structured_error() -> None:
    """Regions not in the four-region matrix must fail-closed with
    the documented error code (e.g., zz / latam / apac stub)."""
    with pytest.raises(SandboxProviderNotRegistered) as exc_info:
        get_sandbox_provider("zz_unknown_region")
    assert exc_info.value.code == ErrorCode.SANDBOX_PROVIDER_NOT_REGISTERED
    assert exc_info.value.region_code == "zz_unknown_region"


def test_unregistered_region_or_none_helper_returns_none() -> None:
    assert get_sandbox_provider_or_none("zz_unknown") is None


def test_india_provider_preserves_india_semantics_bit_identically() -> None:
    """Phase 2 invariant: the India sandbox provider must return the
    same India semantics the legacy hardcoded paths emit, so callers
    that migrate to dispatcher-only flow do not change India behavior."""
    provider = get_sandbox_provider("india")
    assert provider.base_currency() == "INR"
    assert provider.supported_products() == {"MIS", "CNC", "NRML"}
    assert provider.partial_fills_supported() is False
    assert provider.initial_funds() == Decimal("1000000.00")

    rules = provider.position_lifecycle_rules()
    assert isinstance(rules, ProviderRules)
    assert rules.settlement_days_equity == 1  # India T+1
    assert rules.settlement_days_options == 1
    assert rules.day_trade_close_required is True  # India MIS
    assert rules.overnight_allowed is True  # India CNC/NRML
    assert rules.partial_fills_supported is False

    # MIS auto-square-off on a deterministic date (skip current-date
    # equality so the assertion is stable across timezones / DST).
    sq = provider.squareoff_time_for_product("MIS", "NSE", date(2026, 4, 15))
    assert sq is not None
    assert sq.year == 2026 and sq.month == 4 and sq.day == 15
    assert sq.hour == 15 and sq.minute == 15
    assert sq.tzinfo is not None  # tz-aware

    # CNC / NRML have no auto-square-off.
    assert provider.squareoff_time_for_product("CNC", "NSE", date(2026, 4, 15)) is None
    assert provider.squareoff_time_for_product("NRML", "NSE", date(2026, 4, 15)) is None


def test_us_provider_returns_us_semantics() -> None:
    """The mock US provider must NOT return India values, even when
    accessed through the same dispatcher API. This pins the negative
    invariant that broker → region routing is doing real work."""
    provider = get_sandbox_provider("us")
    assert provider.base_currency() == "USD"
    assert provider.base_currency() != "INR"
    products = provider.supported_products()
    # US products must not be the India set.
    assert products != {"MIS", "CNC", "NRML"}


def test_dispatcher_is_case_insensitive_on_region_code() -> None:
    """Operators set region codes via env vars; we tolerate any case."""
    a = get_sandbox_provider("india")
    b = get_sandbox_provider("INDIA")
    c = get_sandbox_provider("India")
    assert a is b is c
