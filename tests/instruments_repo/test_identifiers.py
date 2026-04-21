"""Instrument identifier semantics — including ISIN shared across venues."""

from __future__ import annotations

import pytest

from database.instruments_repo import (
    identifier_add,
    identifier_resolve,
    instruments_create,
    venues_upsert,
)


@pytest.fixture
def venues(fresh_db):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("BSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")


def test_isin_shared_across_two_venues(venues) -> None:
    """The same ISIN points to different instruments on NSE and BSE."""
    nse_instrument = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    bse_instrument = instruments_create(
        venue_code="BSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )

    # Same ISIN, different venues. broker_code omitted — the ISIN is
    # venue-agnostic metadata, so the venue is the narrowing filter.
    identifier_add(nse_instrument.instrument_id, "ISIN", "INE002A01018", venue_code="NSE")
    identifier_add(bse_instrument.instrument_id, "ISIN", "INE002A01018", venue_code="BSE")

    nse_matches = identifier_resolve("ISIN", "INE002A01018", venue_code="NSE")
    assert len(nse_matches) == 1
    assert nse_matches[0].instrument_id == nse_instrument.instrument_id

    bse_matches = identifier_resolve("ISIN", "INE002A01018", venue_code="BSE")
    assert len(bse_matches) == 1
    assert bse_matches[0].instrument_id == bse_instrument.instrument_id


def test_resolver_narrows_by_broker(venues) -> None:
    """The same (identifier_type, value) can belong to different brokers."""
    a = instruments_create(
        venue_code="NSE",
        canonical_symbol="SBIN",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    b = instruments_create(
        venue_code="BSE",
        canonical_symbol="SBIN",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    identifier_add(
        a.instrument_id, "BROKER_TOKEN", "12345", broker_code="zerodha", venue_code="NSE"
    )
    identifier_add(
        b.instrument_id, "BROKER_TOKEN", "67890", broker_code="zerodha", venue_code="BSE"
    )

    match = identifier_resolve(
        "BROKER_TOKEN", "12345", broker_code="zerodha", venue_code="NSE"
    )
    assert len(match) == 1
    assert match[0].instrument_id == a.instrument_id


def test_resolver_no_match_returns_empty(venues) -> None:
    assert identifier_resolve("FIGI", "BBG000000000") == []


def test_null_broker_code_matches_only_null_broker_code(venues) -> None:
    """An identifier inserted without broker_code is venue-agnostic; a
    query with broker_code=None must match it, and a query with a
    specific broker_code must NOT."""
    i = instruments_create(
        venue_code="NSE",
        canonical_symbol="TCS",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    identifier_add(i.instrument_id, "ISIN", "INE467B01029", venue_code="NSE")

    # broker_code=None query → match
    no_broker = identifier_resolve("ISIN", "INE467B01029", venue_code="NSE")
    assert len(no_broker) == 1

    # broker_code="zerodha" query → no match
    with_broker = identifier_resolve(
        "ISIN", "INE467B01029", broker_code="zerodha", venue_code="NSE"
    )
    assert with_broker == []
