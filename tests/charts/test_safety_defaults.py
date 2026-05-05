"""Phase 6 — D-05 safety defaults resolution."""

from __future__ import annotations

from decimal import Decimal

from services.charts.safety_defaults import (
    DEFAULT_MAX_NOTIONAL_INR,
    DEFAULT_MAX_NOTIONAL_USD,
    DEFAULT_MAX_ORDER_SIZE,
    defaults_for_broker_currency,
    resolve_max_notional,
)


def test_default_constants_match_d05():
    assert DEFAULT_MAX_ORDER_SIZE == 100
    assert DEFAULT_MAX_NOTIONAL_USD == Decimal("100000")
    assert DEFAULT_MAX_NOTIONAL_INR == Decimal("1000000")


def test_resolve_max_notional_usd():
    assert resolve_max_notional("USD") == Decimal("100000")


def test_resolve_max_notional_inr():
    assert resolve_max_notional("INR") == Decimal("1000000")


def test_resolve_max_notional_unknown_returns_none_without_fx():
    assert resolve_max_notional("EUR") is None


def test_resolve_max_notional_unknown_with_fx():
    # 1 EUR = 1.1 USD → cap is 100_000 / 1.1 ≈ 90909.09 EUR
    cap = resolve_max_notional("EUR", Decimal("1.1"))
    assert cap is not None
    assert cap > Decimal("90000")


def test_defaults_for_broker_currency_usd():
    d = defaults_for_broker_currency("USD")
    assert d.max_order_size == 100
    assert d.max_notional == Decimal("100000")
    assert d.currency == "USD"
    assert d.kill_switch is False
    assert d.live_mode_enabled is False


def test_defaults_for_broker_currency_inr():
    d = defaults_for_broker_currency("INR")
    assert d.max_notional == Decimal("1000000")
    assert d.currency == "INR"


def test_defaults_for_unknown_currency_caps_to_none():
    d = defaults_for_broker_currency("EUR")
    assert d.max_notional is None
