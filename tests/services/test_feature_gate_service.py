"""Phase 6 — services/feature_gate_service.

Verifies the resolution order, the env override, and the per-region
flag lookup paths.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)


def test_default_active_region_is_india_when_nothing_set() -> None:
    from services.feature_gate_service import active_region_code

    # No broker session, no explicit settings, no env. Falls back to india.
    assert active_region_code() == "india"


def test_env_override_shortcircuits_resolution(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.feature_gate_service import active_region_code, is_india_region_active

    assert active_region_code() == "us"
    assert is_india_region_active() is False


def test_india_region_default_is_active(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.feature_gate_service import is_india_region_active

    assert is_india_region_active() is True


def test_is_feature_enabled_for_india_uses_plugin(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.feature_gate_service import is_feature_enabled_for_active_region

    # india plugin sets option_chain_enabled=True
    assert is_feature_enabled_for_active_region("option_chain_enabled") is True


def test_is_feature_enabled_for_us_returns_false(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    from services.feature_gate_service import is_feature_enabled_for_active_region

    # us plugin sets option_chain_enabled=False
    assert is_feature_enabled_for_active_region("option_chain_enabled") is False


def test_is_feature_enabled_unknown_flag_returns_default(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    from services.feature_gate_service import is_feature_enabled_for_active_region

    assert is_feature_enabled_for_active_region("never_declared") is False
    assert is_feature_enabled_for_active_region("never_declared", default=True) is True
