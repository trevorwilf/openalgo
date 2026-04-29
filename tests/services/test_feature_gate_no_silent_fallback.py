"""Phase 2 v4 / v6 Phase 4-bis — services.feature_gate_service
no-silent-fallback tests.

Confirms that:

* ``active_region_code()`` raises :class:`RegionResolutionError` when
  no broker / settings region is resolvable. v6 Phase 4-bis retired
  the ``legacy_india_fallback=True`` opt-in; the function now ALWAYS
  raises in this case.
* ``is_india_region_active()`` returns ``False`` (capability-driven —
  no broker means no India).
* ``is_feature_enabled_for_active_region()`` returns the caller's
  ``default`` (never raises).
"""

from __future__ import annotations

import os

import pytest

from domain.errors import RegionResolutionError
from services import feature_gate_service


@pytest.fixture(autouse=True)
def _clear_test_region(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
    yield


def test_active_region_code_raises_when_no_context(monkeypatch):
    # Force the chain to fail at every step.
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )
    with pytest.raises(RegionResolutionError):
        feature_gate_service.active_region_code()


def test_is_india_region_active_returns_false_when_no_broker(monkeypatch):
    """v6 Phase 4-bis (ADR 0031): is_india_region_active is now
    capability-driven. With no broker connected and no default region
    configured, it returns False — there is no longer a silent India
    fallback."""
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )
    # Never raises — catches RegionResolutionError internally and
    # returns False instead of falling back to "india".
    assert feature_gate_service.is_india_region_active() is False


def test_is_feature_enabled_passes_default_to_region_lookup(monkeypatch):
    """v6 Phase 4-bis: when a broker IS connected (region resolves),
    the default flows through to the region lookup. When no region
    resolves, the function short-circuits to ``default`` without
    calling the lookup (covered separately below)."""
    # Force the resolution chain to return a region.
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: "india",  # Settings default resolves to india
    )
    seen_defaults: list[bool] = []

    def _fake(region, flag, default=False):
        seen_defaults.append(default)
        return default

    monkeypatch.setattr(
        "services.market_region_service.is_region_feature_enabled",
        _fake,
    )
    assert feature_gate_service.is_feature_enabled_for_active_region("foo") is False
    assert (
        feature_gate_service.is_feature_enabled_for_active_region("foo", default=True)
        is True
    )
    assert seen_defaults == [False, True]


def test_is_feature_enabled_returns_default_when_no_region_resolves(monkeypatch):
    """v6 Phase 4-bis: when no region resolves,
    is_feature_enabled_for_active_region short-circuits to ``default``
    without calling the region lookup."""
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )

    def _should_not_be_called(*a, **k):
        raise AssertionError("region lookup should not be called when no region resolves")

    monkeypatch.setattr(
        "services.market_region_service.is_region_feature_enabled",
        _should_not_be_called,
    )
    assert feature_gate_service.is_feature_enabled_for_active_region("foo") is False
    assert (
        feature_gate_service.is_feature_enabled_for_active_region("foo", default=True)
        is True
    )


def test_is_feature_enabled_swallows_lookup_errors(monkeypatch):
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )

    def _boom(*a, **k):
        raise RuntimeError("region plugin missing")

    monkeypatch.setattr(
        "services.market_region_service.is_region_feature_enabled",
        _boom,
    )
    assert feature_gate_service.is_feature_enabled_for_active_region("foo") is False
    assert (
        feature_gate_service.is_feature_enabled_for_active_region("foo", default=True)
        is True
    )


def test_no_module_level_fallback_region_constant() -> None:
    # The constant has been removed in v4 Phase 2.
    assert not hasattr(feature_gate_service, "_FALLBACK_REGION"), (
        "services.feature_gate_service._FALLBACK_REGION must not exist "
        "after v4 Phase 2 (ADR 0023 invariant 1)."
    )
