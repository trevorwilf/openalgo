"""Phase 8 v4 (ADR 0026) — SandboxProvider contract conformance tests.

Both shipped providers (India + US) implement every Protocol method
and the dispatcher resolves them by region. Fail-closed for
unregistered regions.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from services.sandbox import dispatcher
from services.sandbox.providers.base import SandboxProvider
from services.sandbox.providers.india import IndiaSandboxProvider
from services.sandbox.providers.us import USSandboxProvider


def test_india_provider_implements_contract():
    p = IndiaSandboxProvider()
    assert isinstance(p, SandboxProvider)
    assert p.region_code == "india"
    assert p.base_currency() == "INR"
    assert p.initial_funds() == Decimal("1000000.00")
    assert p.partial_fills_supported() is False
    assert p.supported_products() == {"MIS", "CNC", "NRML"}


def test_us_provider_implements_contract():
    p = USSandboxProvider()
    assert isinstance(p, SandboxProvider)
    assert p.region_code == "us"
    assert p.base_currency() == "USD"
    assert p.initial_funds() == Decimal("100000.00")
    assert p.partial_fills_supported() is True
    assert p.supported_products() == {"DAY_TRADE", "OVERNIGHT", "MARGIN"}


def test_us_provider_t2_equity_settlement():
    p = USSandboxProvider()
    # Friday 2026-04-17 → settles Tuesday 2026-04-21 (skip Sat/Sun).
    from types import SimpleNamespace

    order = SimpleNamespace(asset_class=SimpleNamespace(value="EQUITY"))
    assert p.settlement_date_for_order(order, date(2026, 4, 17)) == date(2026, 4, 21)


def test_us_provider_t1_options_settlement():
    p = USSandboxProvider()
    from types import SimpleNamespace

    order = SimpleNamespace(asset_class=SimpleNamespace(value="OPTION"))
    assert p.settlement_date_for_order(order, date(2026, 4, 15)) == date(2026, 4, 16)


def test_india_provider_t1_settlement_for_anything():
    p = IndiaSandboxProvider()
    from types import SimpleNamespace

    order = SimpleNamespace(asset_class=SimpleNamespace(value="EQUITY"))
    assert p.settlement_date_for_order(order, date(2026, 4, 15)) == date(2026, 4, 16)


def test_india_mis_squareoff_at_15_15():
    p = IndiaSandboxProvider()
    sq = p.squareoff_time_for_product("MIS", "NSE", date(2026, 4, 15))
    assert sq is not None
    assert sq.hour == 15 and sq.minute == 15
    assert str(sq.tzinfo) == "Asia/Kolkata"


def test_india_cnc_no_squareoff():
    p = IndiaSandboxProvider()
    assert p.squareoff_time_for_product("CNC", "NSE", date(2026, 4, 15)) is None


def test_us_day_trade_squareoff_at_16_00():
    p = USSandboxProvider()
    sq = p.squareoff_time_for_product("DAY_TRADE", "XNYS", date(2026, 4, 15))
    assert sq is not None
    assert sq.hour == 16 and sq.minute == 0
    assert str(sq.tzinfo) == "America/New_York"


def test_us_overnight_no_squareoff():
    p = USSandboxProvider()
    assert p.squareoff_time_for_product("OVERNIGHT", "XNYS", date(2026, 4, 15)) is None


def test_dispatcher_resolves_india_provider():
    dispatcher.clear_sandbox_registry_for_tests()
    dispatcher.install_default_sandbox_providers()
    p = dispatcher.get_sandbox_provider("india")
    assert isinstance(p, IndiaSandboxProvider)


def test_dispatcher_resolves_us_provider():
    dispatcher.clear_sandbox_registry_for_tests()
    dispatcher.install_default_sandbox_providers()
    p = dispatcher.get_sandbox_provider("us")
    assert isinstance(p, USSandboxProvider)


def test_dispatcher_failclosed_for_unknown_region():
    dispatcher.clear_sandbox_registry_for_tests()
    dispatcher.install_default_sandbox_providers()
    with pytest.raises(dispatcher.SandboxProviderNotRegistered) as exc:
        dispatcher.get_sandbox_provider("eu")
    assert exc.value.code == "sandbox_provider_not_registered"


def test_dispatcher_get_or_none_returns_none_for_unknown():
    dispatcher.clear_sandbox_registry_for_tests()
    dispatcher.install_default_sandbox_providers()
    assert dispatcher.get_sandbox_provider_or_none("eu") is None
