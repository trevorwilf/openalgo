"""Phase 6 — services/feature_gate_service.

Verifies the resolution order, the env override, and the per-region
flag lookup paths.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)
    # v5 Phase 2 — explicitly populate the region catalog so tests
    # that read region feature flags don't depend on prior tests
    # having lazy-loaded it. Without this, running this file in
    # isolation produces "False" feature reads because
    # `utils.region_loader._market_regions` starts empty and
    # `get_market_region()` does not auto-load.
    from utils.region_loader import load_market_regions

    load_market_regions()


def test_default_active_region_raises_without_legacy_fallback(monkeypatch) -> None:
    """v4 Phase 2 (ADR 0023 invariant 1) removed the silent India
    fallback. ``active_region_code()`` now raises
    ``RegionResolutionError`` when nothing resolves and the caller has
    not opted into the legacy India compatibility path.

    v5 Phase 2 — make the test robust against the installed region
    catalog by monkeypatching ``resolve_default_market_region_code``
    to return None. Previously this test was order-dependent: the
    real resolver returns ``"india"`` whenever the India region plugin
    exists in ``market_regions/`` (which it always does in this repo),
    masking the v4 invariant 1 boundary unless a sibling test had
    already monkeypatched the same function in this process.
    """
    from domain.errors import RegionResolutionError
    from services import feature_gate_service
    from services.feature_gate_service import active_region_code

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
        active_region_code()


def test_default_active_region_legacy_fallback_returns_india(monkeypatch) -> None:
    """The opt-in legacy India compatibility path still returns
    ``"india"`` (used by ``is_india_region_active`` and the named
    services that have not yet migrated to provider-pluggable
    dispatch).

    Same v5 Phase 2 monkeypatch hardening as above so the assertion
    isn't accidentally satisfied by the installed-catalog fallback.
    """
    from services import feature_gate_service
    from services.feature_gate_service import active_region_code

    monkeypatch.setattr(
        feature_gate_service,
        "_current_broker_session_value",
        lambda: None,
    )
    monkeypatch.setattr(
        "services.market_region_service.resolve_default_market_region_code",
        lambda: None,
    )
    assert active_region_code(legacy_india_fallback=True) == "india"


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
