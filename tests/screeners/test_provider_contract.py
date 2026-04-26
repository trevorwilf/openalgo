"""Phase 10 v4 (ADR 0028) — ScreenerProvider contract conformance tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.screeners import dispatcher
from services.screeners.providers.base import (
    ScreenerConfig,
    ScreenerProvider,
    ScreenerSignal,
)
from services.screeners.providers.india import ChartinkScreenerProvider


def test_chartink_implements_contract():
    p = ChartinkScreenerProvider()
    assert isinstance(p, ScreenerProvider)
    assert p.provider_code == "chartink"
    assert p.region_code == "india"
    assert p.supported_venues == ["NSE", "BSE"]


def test_chartink_validate_payload_basic_buy():
    p = ChartinkScreenerProvider()
    signal = p.validate_webhook_payload({
        "stocks": "SBIN,RELIANCE,TCS",
        "trigger_prices": "525.5,2840.0,3500.0",
        "scan_name": "Bullish Pattern",
        "alert_name": "Bullish Pattern Alert",
    })
    assert signal.signal_type == "buy"
    assert signal.symbols == ["SBIN", "RELIANCE", "TCS"]
    assert signal.price == Decimal("525.5")
    assert signal.metadata["scan_name"] == "Bullish Pattern"


def test_chartink_validate_sell_signal():
    p = ChartinkScreenerProvider()
    signal = p.validate_webhook_payload({
        "stocks": "INFY",
        "scan_name": "Bearish Reversal",
    })
    assert signal.signal_type == "sell"


def test_chartink_validate_exit_signal():
    p = ChartinkScreenerProvider()
    signal = p.validate_webhook_payload({
        "stocks": "TATAMOTORS",
        "alert_name": "Square off all positions",
    })
    assert signal.signal_type == "exit"


def test_chartink_validate_missing_stocks_raises():
    p = ChartinkScreenerProvider()
    with pytest.raises(ValueError, match="missing 'stocks'"):
        p.validate_webhook_payload({})


def test_chartink_validate_non_dict_payload_raises():
    p = ChartinkScreenerProvider()
    with pytest.raises(ValueError, match="must be a dict"):
        p.validate_webhook_payload("not a dict")  # type: ignore[arg-type]


def test_chartink_supported_signal_types():
    p = ChartinkScreenerProvider()
    assert p.supported_signal_types() == {"buy", "sell", "exit"}


def test_chartink_map_signal_to_orders_buy():
    p = ChartinkScreenerProvider()
    signal = ScreenerSignal(
        signal_type="buy",
        symbols=["SBIN", "RELIANCE"],
        price=Decimal("525.5"),
    )
    config = ScreenerConfig(
        quantity=Decimal("10"),
        product="MIS",
        venue_code="NSE",
        order_type="MARKET",
    )
    orders = p.map_signal_to_orders(signal, config)
    assert len(orders) == 2
    assert orders[0].instrument.canonical_symbol == "SBIN"
    assert orders[0].instrument.venue_code == "NSE"
    assert orders[0].quantity == Decimal("10")
    # MARKET order should not have a price.
    assert orders[0].price is None


def test_chartink_map_signal_limit_keeps_price():
    p = ChartinkScreenerProvider()
    signal = ScreenerSignal(
        signal_type="buy",
        symbols=["SBIN"],
        price=Decimal("525.5"),
    )
    config = ScreenerConfig(
        quantity=Decimal("10"),
        product="MIS",
        order_type="LIMIT",
    )
    orders = p.map_signal_to_orders(signal, config)
    assert orders[0].price == Decimal("525.5")


# Dispatcher ---------------------------------------------------------


def test_dispatcher_resolves_chartink():
    dispatcher.clear_screener_registry_for_tests()
    dispatcher.install_default_screener_providers()
    p = dispatcher.get_screener_provider("chartink")
    assert isinstance(p, ChartinkScreenerProvider)


def test_dispatcher_failclosed_for_unknown_provider():
    dispatcher.clear_screener_registry_for_tests()
    dispatcher.install_default_screener_providers()
    with pytest.raises(dispatcher.ScreenerProviderNotRegistered) as exc:
        dispatcher.get_screener_provider("tradingview")
    assert exc.value.code == "screener_provider_not_registered"


def test_dispatcher_get_or_none_returns_none_for_unknown():
    dispatcher.clear_screener_registry_for_tests()
    dispatcher.install_default_screener_providers()
    assert dispatcher.get_screener_provider_or_none("tradingview") is None
