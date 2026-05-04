"""T-23 + T-24 (v7 Phase 6-bis) — real EU/UK options providers.

Replaces the previous ``OPTION_CHAIN_DISABLED_IN_REGION`` stubs
with actual OCC-style 21-character symbol parsing + the
third-Friday monthly expiry convention. Greeks / IV delegate to
``domain.options_math`` (the same shared computation as US).

Real EU production (Eurex) and UK production (ICE Europe) use
their own native symbol formats; the OCC normalization at the
OpenAlgo layer matches how multi-region broker plugins like
Interactive Brokers represent them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def test_eu_options_parse_and_format_round_trip():
    from services.options.providers.eu import EUOptionsProvider

    provider = EUOptionsProvider()
    symbol = "SAP   240419C00185000"
    contract = provider.parse_option_symbol(symbol)
    assert contract.underlying == "SAP"
    assert contract.expiry == date(2024, 4, 19)
    assert contract.strike == Decimal("185")
    assert contract.currency == "EUR"
    assert contract.venue_code == "XEUR"
    assert provider.format_option_symbol(contract) == symbol


def test_uk_options_parse_with_gbp_and_ifeu():
    from services.options.providers.uk import UKOptionsProvider

    provider = UKOptionsProvider()
    symbol = "VOD   240419P00200000"
    contract = provider.parse_option_symbol(symbol)
    assert contract.underlying == "VOD"
    assert contract.right.name == "PUT"
    assert contract.strike == Decimal("200")
    assert contract.currency == "GBP"
    assert contract.venue_code == "IFEU"
    assert contract.lot_size == 1000  # ICE Europe equity options


def test_eu_options_lists_third_friday_expiries():
    from services.options.providers.eu import EUOptionsProvider

    provider = EUOptionsProvider()
    expiries = provider.list_expiries("SAP", date(2026, 1, 1))
    assert len(expiries) == 12
    # Third Friday of January 2026 is the 16th.
    assert expiries[0] == date(2026, 1, 16)
    # Each expiry should be a Friday.
    for exp in expiries:
        assert exp.weekday() == 4


def test_uk_options_lists_third_friday_expiries():
    from services.options.providers.uk import UKOptionsProvider

    provider = UKOptionsProvider()
    expiries = provider.list_expiries("VOD", date(2026, 1, 1))
    assert len(expiries) == 12
    assert expiries[0] == date(2026, 1, 16)


def test_eu_uk_supported_strategies_non_empty():
    from services.options.providers.eu import EUOptionsProvider
    from services.options.providers.uk import UKOptionsProvider

    eu = EUOptionsProvider()
    uk = UKOptionsProvider()
    # The previous stubs returned set() — real providers return
    # at least the basic four-strategy set.
    assert "STRADDLE" in eu.supported_strategies()
    assert "STRADDLE" in uk.supported_strategies()
