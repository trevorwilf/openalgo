"""Phase 2 v4 — services.feature_gate_service no-silent-fallback tests.

Confirms that:

* ``active_region_code()`` raises :class:`RegionResolutionError` when
  no broker / settings region is resolvable AND no legacy fallback is
  opted in (the v4 default).
* ``active_region_code(legacy_india_fallback=True)`` returns
  ``"india"`` in the same situation (the named, deprecated path used
  by services that have not yet migrated to provider-pluggable
  dispatch).
* ``is_india_region_active()`` and
  ``is_feature_enabled_for_active_region()`` keep working without
  raising — they internally pass ``legacy_india_fallback=True``.
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


def test_active_region_code_legacy_fallback_returns_india(monkeypatch):
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )
    region = feature_gate_service.active_region_code(legacy_india_fallback=True)
    assert region == "india"


def test_is_india_region_active_never_raises(monkeypatch):
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )
    # Must not raise — uses the legacy_india_fallback internally.
    assert feature_gate_service.is_india_region_active() is True


def test_is_feature_enabled_passes_default_to_region_lookup(monkeypatch):
    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
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
