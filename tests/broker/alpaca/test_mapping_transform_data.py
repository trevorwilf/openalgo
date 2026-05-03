"""Alpaca mapping/transform_data — vocabulary round-trip."""

from __future__ import annotations

from broker.alpaca.mapping.transform_data import (
    ALPACA_EXCHANGE_TO_VENUE,
    ALPACA_TAPE_TO_VENUE,
    ALPACA_TO_ORDER_TYPE,
    ALPACA_TO_SIDE,
    ALPACA_TO_TIF,
    ORDER_TYPE_TO_ALPACA,
    SIDE_TO_ALPACA,
    SUPPORTED_ORDER_TYPES,
    SUPPORTED_TIF,
    SUPPORTED_VENUES,
    TIF_TO_ALPACA,
    VENUE_TO_ALPACA_EXCHANGE,
    from_alpaca_symbol,
    map_order_side,
    map_order_type,
    map_time_in_force,
    to_alpaca_symbol,
    venue_from_alpaca_exchange,
    venue_from_alpaca_tape,
)
from domain.enums import OrderSide, OrderType, TimeInForce


# ---------------------------------------------------------------------------
# Venue mapping
# ---------------------------------------------------------------------------


def test_venue_from_alpaca_exchange_canonical_codes():
    assert venue_from_alpaca_exchange("NASDAQ") == "XNAS"
    assert venue_from_alpaca_exchange("NYSE") == "XNYS"
    assert venue_from_alpaca_exchange("ARCA") == "ARCX"
    assert venue_from_alpaca_exchange("BATS") == "BATS"
    assert venue_from_alpaca_exchange("IEX") == "IEXG"


def test_venue_from_alpaca_exchange_amex_folds_to_xnys():
    assert venue_from_alpaca_exchange("AMEX") == "XNYS"


def test_venue_from_alpaca_exchange_otc_folds_to_xnas():
    assert venue_from_alpaca_exchange("OTC") == "XNAS"


def test_venue_from_alpaca_exchange_unmapped_returns_none():
    assert venue_from_alpaca_exchange("PINK") is None
    assert venue_from_alpaca_exchange("") is None
    assert venue_from_alpaca_exchange(None) is None


def test_venue_from_alpaca_exchange_case_insensitive():
    assert venue_from_alpaca_exchange("nasdaq") == "XNAS"
    assert venue_from_alpaca_exchange("  NYSE  ") == "XNYS"


def test_venue_to_alpaca_exchange_round_trip():
    """For canonical venues the round-trip is lossless."""
    for venue in ("XNAS", "XNYS", "ARCX", "BATS", "IEXG"):
        alpaca = VENUE_TO_ALPACA_EXCHANGE[venue]
        assert ALPACA_EXCHANGE_TO_VENUE[alpaca] == venue


def test_venue_from_alpaca_tape_canonical():
    assert venue_from_alpaca_tape("V") == "IEXG"
    assert venue_from_alpaca_tape("Q") == "XNAS"
    assert venue_from_alpaca_tape("N") == "XNYS"
    assert venue_from_alpaca_tape("P") == "ARCX"
    assert venue_from_alpaca_tape("Z") == "BATS"


def test_venue_from_alpaca_tape_unknown_falls_back_to_xnas():
    assert venue_from_alpaca_tape("X") == "XNAS"
    assert venue_from_alpaca_tape(None) == "XNAS"
    assert venue_from_alpaca_tape("") == "XNAS"


def test_supported_venues_subset_of_canonical():
    for venue in SUPPORTED_VENUES:
        assert venue in ALPACA_EXCHANGE_TO_VENUE.values()


# ---------------------------------------------------------------------------
# Order vocabulary
# ---------------------------------------------------------------------------


def test_map_order_side():
    assert map_order_side(OrderSide.BUY) == "buy"
    assert map_order_side(OrderSide.SELL) == "sell"


def test_map_order_type():
    assert map_order_type(OrderType.MARKET) == "market"
    assert map_order_type(OrderType.LIMIT) == "limit"


def test_map_time_in_force():
    assert map_time_in_force(TimeInForce.DAY) == "day"
    assert map_time_in_force(TimeInForce.GTC) == "gtc"


def test_side_round_trip():
    for side in (OrderSide.BUY, OrderSide.SELL):
        alpaca_str = SIDE_TO_ALPACA[side]
        assert ALPACA_TO_SIDE[alpaca_str] == side


def test_order_type_round_trip():
    for ot in SUPPORTED_ORDER_TYPES:
        assert ORDER_TYPE_TO_ALPACA[ot] in ALPACA_TO_ORDER_TYPE
        assert ALPACA_TO_ORDER_TYPE[ORDER_TYPE_TO_ALPACA[ot]] == ot


def test_tif_round_trip():
    for tif in SUPPORTED_TIF:
        assert TIF_TO_ALPACA[tif] in ALPACA_TO_TIF
        assert ALPACA_TO_TIF[TIF_TO_ALPACA[tif]] == tif


# ---------------------------------------------------------------------------
# Symbol round-trip
# ---------------------------------------------------------------------------


def test_equity_symbol_round_trip_is_identity():
    assert to_alpaca_symbol("AAPL") == "AAPL"
    assert from_alpaca_symbol("AAPL") == "AAPL"
    assert from_alpaca_symbol(to_alpaca_symbol("TSLA")) == "TSLA"


def test_crypto_symbol_uses_slash_in_alpaca_form():
    assert to_alpaca_symbol("BTC-USD", asset_class="SPOT") == "BTC/USD"
    assert from_alpaca_symbol("BTC/USD", asset_class="SPOT") == "BTC-USD"
    assert from_alpaca_symbol(
        to_alpaca_symbol("ETH-USD", asset_class="SPOT"), asset_class="SPOT"
    ) == "ETH-USD"


def test_crypto_default_asset_class_keeps_dash():
    """Without the SPOT asset_class hint the helper does NOT translate
    — that's the safe default for callers that don't supply a hint.
    """
    assert to_alpaca_symbol("BTC-USD") == "BTC-USD"
