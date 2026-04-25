"""Phase 6 — sandbox region gate (ADR 0011).

Sandbox semantics (T+1, MIS/CNC/NRML, IST square-off) are India-only
until non-India sandbox policies are seeded. The gate fails closed at
:class:`OrderManager` construction time when the active region is
not india.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("MARKET_REGION_FOR_TESTS", raising=False)


def test_india_region_constructs_order_manager(monkeypatch) -> None:
    """India region (default) — OrderManager constructs without error.

    The constructor only enforces the gate; it does not need a working
    DB to instantiate.
    """
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    # Stub out FundManager so we don't need a DB.
    import sandbox.order_manager as om

    monkeypatch.setattr(om, "FundManager", lambda user_id: object())
    mgr = om.OrderManager(user_id="test-user")
    assert mgr.user_id == "test-user"


def test_us_region_raises_at_construction(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    import sandbox.order_manager as om
    from domain.errors import SandboxNotAvailableInRegion

    monkeypatch.setattr(om, "FundManager", lambda user_id: object())
    with pytest.raises(SandboxNotAvailableInRegion) as exc:
        om.OrderManager(user_id="test-user")
    assert exc.value.active_region == "us"
    assert exc.value.code == "sandbox_region_unsupported"


def test_eu_region_raises_at_construction(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "eu")
    import sandbox.order_manager as om
    from domain.errors import SandboxNotAvailableInRegion

    monkeypatch.setattr(om, "FundManager", lambda user_id: object())
    with pytest.raises(SandboxNotAvailableInRegion):
        om.OrderManager(user_id="test-user")
