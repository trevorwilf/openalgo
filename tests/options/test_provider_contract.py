"""Phase 9 v4 (ADR 0027) — OptionsProvider contract conformance tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domain.options import OptionContract, OptionRight
from services.options import dispatcher
from services.options.providers.base import OptionsProvider
from services.options.providers.india import IndiaOptionsProvider
from services.options.providers.us import USOptionsProvider


def test_india_provider_implements_contract():
    p = IndiaOptionsProvider()
    assert isinstance(p, OptionsProvider)
    assert p.region_code == "india"


def test_us_provider_implements_contract():
    p = USOptionsProvider()
    assert isinstance(p, OptionsProvider)
    assert p.region_code == "us"


# India parsing -------------------------------------------------------


def test_india_parse_nifty_call():
    p = IndiaOptionsProvider()
    contract = p.parse_option_symbol("NIFTY28MAR2420800CE")
    assert contract.underlying == "NIFTY"
    assert contract.expiry == date(2024, 3, 28)
    assert contract.right == OptionRight.CALL
    assert contract.strike == Decimal("20800")
    assert contract.lot_size == 50
    assert contract.currency == "INR"
    assert contract.venue_code == "NFO"


def test_india_parse_banknifty_put():
    p = IndiaOptionsProvider()
    contract = p.parse_option_symbol("BANKNIFTY24APR2447500PE")
    assert contract.underlying == "BANKNIFTY"
    assert contract.expiry == date(2024, 4, 24)
    assert contract.right == OptionRight.PUT
    assert contract.strike == Decimal("47500")
    assert contract.lot_size == 15


def test_india_parse_invalid_raises():
    p = IndiaOptionsProvider()
    with pytest.raises(ValueError, match="grammar mismatch"):
        p.parse_option_symbol("AAPL  240419C00185000")  # OSI shape, not India


def test_india_format_round_trip():
    p = IndiaOptionsProvider()
    original = "NIFTY28MAR2420800CE"
    contract = p.parse_option_symbol(original)
    assert p.format_option_symbol(contract) == original


# US parsing ----------------------------------------------------------


def test_us_parse_aapl_call():
    p = USOptionsProvider()
    contract = p.parse_option_symbol("AAPL  240419C00185000")
    assert contract.underlying == "AAPL"
    assert contract.expiry == date(2024, 4, 19)
    assert contract.right == OptionRight.CALL
    assert contract.strike == Decimal("185.000")
    assert contract.lot_size == 100
    assert contract.multiplier == 100
    assert contract.currency == "USD"
    assert contract.venue_code == "OPRA"


def test_us_parse_msft_put():
    p = USOptionsProvider()
    contract = p.parse_option_symbol("MSFT  240517P00400000")
    assert contract.underlying == "MSFT"
    assert contract.right == OptionRight.PUT
    assert contract.strike == Decimal("400.000")


def test_us_parse_wrong_length_raises():
    p = USOptionsProvider()
    with pytest.raises(ValueError, match="OSI grammar mismatch"):
        p.parse_option_symbol("NIFTY28MAR2420800CE")


def test_us_format_round_trip():
    p = USOptionsProvider()
    original = "AAPL  240419C00185000"
    contract = p.parse_option_symbol(original)
    assert p.format_option_symbol(contract) == original


# Greeks --------------------------------------------------------------


def test_us_provider_compute_greeks():
    from domain.options import MarketSnapshot

    p = USOptionsProvider()
    contract = p.parse_option_symbol("AAPL  240419C00185000")
    market = MarketSnapshot(
        underlying_price=Decimal("190"),
        risk_free_rate=Decimal("0.05"),
        asof=date(2024, 1, 19),
    )
    greeks = p.compute_greeks(contract, market, Decimal("0.30"))
    assert greeks.delta > Decimal("0")
    assert greeks.gamma > Decimal("0")
    assert greeks.vega > Decimal("0")


def test_india_provider_compute_greeks():
    from domain.options import MarketSnapshot

    p = IndiaOptionsProvider()
    contract = p.parse_option_symbol("NIFTY28MAR2420800CE")
    market = MarketSnapshot(
        underlying_price=Decimal("21000"),
        risk_free_rate=Decimal("0.07"),
        asof=date(2024, 1, 28),
    )
    greeks = p.compute_greeks(contract, market, Decimal("0.15"))
    assert greeks.delta > Decimal("0")
    assert greeks.gamma > Decimal("0")


# Dispatcher ----------------------------------------------------------


def test_dispatcher_resolves_india():
    dispatcher.clear_options_registry_for_tests()
    dispatcher.install_default_options_providers()
    assert isinstance(dispatcher.get_options_provider("india"), IndiaOptionsProvider)


def test_dispatcher_resolves_us():
    dispatcher.clear_options_registry_for_tests()
    dispatcher.install_default_options_providers()
    assert isinstance(dispatcher.get_options_provider("us"), USOptionsProvider)


def test_dispatcher_failclosed_for_unknown():
    dispatcher.clear_options_registry_for_tests()
    dispatcher.install_default_options_providers()
    with pytest.raises(dispatcher.OptionsProviderNotRegistered) as exc:
        dispatcher.get_options_provider("eu")
    assert exc.value.code == "options_provider_not_registered"


# Other contract methods ---------------------------------------------


def test_india_list_expiries_returns_thursdays():
    p = IndiaOptionsProvider()
    expiries = p.list_expiries("NIFTY", date(2024, 1, 1))
    assert len(expiries) == 8
    for e in expiries:
        assert e.weekday() == 3  # Thursday


def test_us_list_expiries_returns_fridays():
    p = USOptionsProvider()
    expiries = p.list_expiries("AAPL", date(2024, 1, 1))
    assert len(expiries) == 8
    for e in expiries:
        assert e.weekday() == 4  # Friday


def test_us_lot_size_is_100():
    p = USOptionsProvider()
    contract = p.parse_option_symbol("AAPL  240419C00185000")
    assert p.lot_size_for(contract) == 100


def test_india_lot_size_for_nifty_is_50():
    p = IndiaOptionsProvider()
    contract = p.parse_option_symbol("NIFTY28MAR2420800CE")
    assert p.lot_size_for(contract) == 50
