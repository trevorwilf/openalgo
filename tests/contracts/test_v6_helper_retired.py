"""Phase 4-bis v6 — `_legacy_india_region_for_compat` retirement contract.

Per ADR 0031, this test asserts that:

* ``_legacy_india_region_for_compat`` is not importable from
  :mod:`services.feature_gate_service`.
* ``legacy_india_fallback`` is not a parameter of
  :func:`active_region_code` or any other public function in
  :mod:`services.feature_gate_service`.

v6 Phase 4-bis (this branch) inverted the markers from "deferred
state" to "retired state". The helper was removed; the parameter
was removed. ``is_india_region_active()`` and
``is_feature_enabled_for_active_region()`` are now capability-driven
(read ``BrokerCapabilities.supported_regions`` directly).

Note: ``services.market_region_service`` retains its own private
``_legacy_india_region_for_compat()`` helper. That one is NOT a
region gate — it is the multi-region catalog's tie-breaker for
unconfigured installs that have multiple region plugins available.
It is allowed to remain.
"""

from __future__ import annotations

import inspect

import pytest


def test_legacy_helper_is_not_importable() -> None:
    """The retired helper must raise ImportError on import attempt."""
    with pytest.raises(ImportError):
        from services.feature_gate_service import (  # noqa: F401
            _legacy_india_region_for_compat,
        )


def test_active_region_code_no_longer_has_legacy_fallback_parameter() -> None:
    """``active_region_code`` no longer accepts ``legacy_india_fallback``."""
    from services.feature_gate_service import active_region_code

    sig = inspect.signature(active_region_code)
    assert "legacy_india_fallback" not in sig.parameters


def test_is_india_region_active_is_capability_driven_for_no_broker_case() -> None:
    """With no broker connected and no default region, the gate
    returns False (not silently True)."""
    from services import feature_gate_service

    # Force the resolution chain to fail at every step.
    original_broker = feature_gate_service._current_broker_session_value
    original_default = None
    try:
        feature_gate_service._current_broker_session_value = lambda: None
        from services import market_region_service

        original_default = market_region_service.resolve_default_market_region_code
        market_region_service.resolve_default_market_region_code = lambda: None
        import os

        os_value = os.environ.get("MARKET_REGION_FOR_TESTS")
        os.environ.pop("MARKET_REGION_FOR_TESTS", None)
        try:
            assert feature_gate_service.is_india_region_active() is False
        finally:
            if os_value is not None:
                os.environ["MARKET_REGION_FOR_TESTS"] = os_value
    finally:
        feature_gate_service._current_broker_session_value = original_broker
        if original_default is not None:
            market_region_service.resolve_default_market_region_code = original_default


def test_market_region_service_helper_retained() -> None:
    """``services.market_region_service._legacy_india_region_for_compat``
    is the multi-region catalog tie-breaker — different concern from
    the retired feature_gate helper. It stays."""
    from services.market_region_service import _legacy_india_region_for_compat

    assert callable(_legacy_india_region_for_compat)
    assert _legacy_india_region_for_compat() == "india"
