"""Phase 2 T-14 — byte-identical relocation of India options grammar.

Pins the relocated DDMMMYY pattern, right codes, lot-size table, index
classification, and equity-index expiry cutoff in
``market_regions/india/options_grammar.py``. The live India options
provider (``services.options.providers.india``) and the legacy options
services (``services.option_symbol_service``) both consume these
literals; the relocation must not change any single value.
"""

from __future__ import annotations

import re

from market_regions.india.options_grammar import (
    DATE_FORMAT,
    DEFAULT_CURRENCY,
    DEFAULT_VENUE_CODE,
    EQUITY_INDEX_EXPIRY_CUTOFF_HHMM,
    INDEX_CLASSIFICATION,
    LOT_SIZES,
    OPTION_GRAMMAR,
    RIGHT_CODES,
    SYMBOL_PATTERN,
)


def test_date_format_is_ddmmmyy():
    assert DATE_FORMAT == "%d%b%y"


def test_right_codes_match_legacy_mapping():
    assert RIGHT_CODES == {"CE": "CALL", "PE": "PUT"}


def test_default_venue_and_currency():
    assert DEFAULT_VENUE_CODE == "NFO"
    assert DEFAULT_CURRENCY == "INR"


def test_lot_sizes_match_provider_snapshot():
    """Snapshot taken from
    ``services.options.providers.india._LOT_SIZES`` at the time of
    relocation. The provider continues to read the same numbers — drift
    here means the relocation lost data."""
    assert LOT_SIZES == {
        "NIFTY": 50,
        "BANKNIFTY": 15,
        "FINNIFTY": 25,
        "MIDCPNIFTY": 75,
        "SENSEX": 10,
        "BANKEX": 15,
    }


def test_index_classification_matches_master_contract_convention():
    assert INDEX_CLASSIFICATION == {"NSE": ["NSE_INDEX"], "BSE": ["BSE_INDEX"]}


def test_equity_index_expiry_cutoff_is_15_30_ist():
    """India equity / index option last-trade time on expiry day is
    15:30 IST (= 10:00 UTC). Frontend strategyMath consumed the same
    value as a hardcoded literal pre-Phase-4."""
    assert EQUITY_INDEX_EXPIRY_CUTOFF_HHMM == (15, 30)


def test_symbol_pattern_round_trips_known_options():
    """Known sample options must match the relocated regex without
    behavior change relative to
    ``services.options.providers.india._INDIA_OPTION_RE``."""
    samples: list[tuple[str, str, str, str, str]] = [
        ("NIFTY28MAR2420800CE", "NIFTY", "28MAR24", "20800", "CE"),
        ("BANKNIFTY24APR2447500PE", "BANKNIFTY", "24APR24", "47500", "PE"),
        ("VEDL25APR24292.5CE", "VEDL", "25APR24", "292.5", "CE"),
    ]
    for sym, underlying, expiry, strike, right in samples:
        m = SYMBOL_PATTERN.match(sym)
        assert m is not None, f"symbol {sym!r} failed to parse"
        assert m.group("underlying") == underlying
        assert m.group("expiry") == expiry
        assert m.group("strike") == strike
        assert m.group("right") == right


def test_symbol_pattern_rejects_non_india_grammar():
    """OCC-21 (US) format and an obvious malformed string both reject."""
    bad_inputs = [
        "AAPL  240419C00150000",  # OCC-21
        "INVALID",
        "NIFTY28MAR24CE",          # missing strike
    ]
    for s in bad_inputs:
        assert SYMBOL_PATTERN.match(s) is None, (
            f"{s!r} should NOT match the India options grammar"
        )


def test_aggregate_option_grammar_payload():
    """The aggregate ``OPTION_GRAMMAR`` dict is the form
    ``MarketRegion.option_grammar`` consumers read. It must round-trip
    every field on the schema."""
    assert OPTION_GRAMMAR["date_format"] == DATE_FORMAT
    assert OPTION_GRAMMAR["right_codes"] == RIGHT_CODES
    assert OPTION_GRAMMAR["default_venue_code"] == DEFAULT_VENUE_CODE
    assert OPTION_GRAMMAR["default_currency"] == DEFAULT_CURRENCY
    assert OPTION_GRAMMAR["symbol_pattern"] == SYMBOL_PATTERN.pattern
    assert OPTION_GRAMMAR["lot_sizes"] == LOT_SIZES
    assert OPTION_GRAMMAR["index_classification"] == INDEX_CLASSIFICATION
    assert (
        OPTION_GRAMMAR["equity_index_expiry_cutoff_hhmm"]
        == EQUITY_INDEX_EXPIRY_CUTOFF_HHMM
    )
    # Re-compile the persisted pattern — round-trip must succeed.
    assert re.compile(OPTION_GRAMMAR["symbol_pattern"]) is not None


def test_provider_lot_size_snapshot_matches():
    """The live India options provider continues to hold its own copy
    of the lot-size table. Until Phase 7 wires the provider to import
    from market_regions.india.options_grammar, this drift-detection
    keeps the two copies aligned."""
    from services.options.providers.india import _LOT_SIZES as provider_lots

    assert provider_lots == LOT_SIZES, (
        "services.options.providers.india._LOT_SIZES drifted from the "
        "relocated market_regions.india.options_grammar.LOT_SIZES. The "
        "two are intentional duplicates while Phase 2 ships data only; "
        "Phase 7 will fold the provider's literal into a single import."
    )
