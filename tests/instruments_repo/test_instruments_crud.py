"""Instrument CRUD including derivative rows with the full uniqueness tuple."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from database.instruments_repo import (
    instruments_create,
    instruments_deactivate,
    instruments_get_by_id,
    instruments_get_by_venue_symbol,
    instruments_search,
    venues_upsert,
)


@pytest.fixture
def nse(fresh_db):
    return venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")


@pytest.fixture
def nfo(fresh_db):
    return venues_upsert("NFO", market_family="IN_STOCK", timezone_name="Asia/Kolkata")


def test_create_cash_equity(nse) -> None:
    i = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
        tick_size=Decimal("0.05"),
        lot_size=1,
        currency="INR",
    )
    assert i.instrument_id is not None
    assert i.canonical_symbol == "RELIANCE"
    assert i.is_active is True


def test_get_by_id(nse) -> None:
    i = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    retrieved = instruments_get_by_id(i.instrument_id)
    assert retrieved is not None
    assert retrieved.canonical_symbol == "INFY"


def test_get_by_venue_symbol_returns_cash_only(nfo) -> None:
    """Derivative rows must NOT be returned by the cash lookup even though
    they share (venue, canonical_symbol)."""
    underlying = instruments_create(
        venue_code="NFO",
        canonical_symbol="NIFTY",
        asset_class="INDEX",
        instrument_kind="CASH",
    )
    # A future whose canonical_symbol happens to collide with the index
    instruments_create(
        venue_code="NFO",
        canonical_symbol="NIFTY",
        asset_class="FUTURE",
        instrument_kind="DERIVATIVE",
        underlying_instrument_id=underlying.instrument_id,
        expiration_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
    )

    cash = instruments_get_by_venue_symbol("NFO", "NIFTY")
    assert cash is not None
    assert cash.instrument_id == underlying.instrument_id
    assert cash.expiration_at is None


def test_derivative_uniqueness_enforced_in_code(nfo) -> None:
    """SQLite treats NULLs as distinct in UniqueConstraint, so the
    repo layer must dedupe explicitly on the derivative tuple."""
    exp = datetime(2026, 4, 24, tzinfo=timezone.utc)
    instruments_create(
        venue_code="NFO",
        canonical_symbol="BANKNIFTY",
        asset_class="OPTION",
        instrument_kind="DERIVATIVE",
        expiration_at=exp,
        option_right="CALL",
        strike=Decimal("50000"),
    )
    with pytest.raises(ValueError, match="already exists"):
        instruments_create(
            venue_code="NFO",
            canonical_symbol="BANKNIFTY",
            asset_class="OPTION",
            instrument_kind="DERIVATIVE",
            expiration_at=exp,
            option_right="CALL",
            strike=Decimal("50000"),
        )


def test_derivative_uniqueness_on_null_tuple(nse) -> None:
    """Two cash rows at the same (venue, symbol) must also collide."""
    instruments_create(
        venue_code="NSE",
        canonical_symbol="TCS",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    with pytest.raises(ValueError, match="already exists"):
        instruments_create(
            venue_code="NSE",
            canonical_symbol="TCS",
            asset_class="EQUITY",
            instrument_kind="CASH",
        )


def test_search_filters(nse) -> None:
    instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    instruments_create(
        venue_code="NSE",
        canonical_symbol="RELCAPITAL",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    instruments_create(
        venue_code="NSE",
        canonical_symbol="TATAMOTORS",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )

    results = instruments_search(query="REL", venue_code="NSE")
    assert [r.canonical_symbol for r in results] == ["RELCAPITAL", "RELIANCE"]

    all_nse = instruments_search(venue_code="NSE", limit=100)
    assert len(all_nse) == 3


def test_search_excludes_inactive(nse) -> None:
    a = instruments_create(
        venue_code="NSE",
        canonical_symbol="A1",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    instruments_create(
        venue_code="NSE",
        canonical_symbol="A2",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    instruments_deactivate(a.instrument_id)

    results = instruments_search(venue_code="NSE")
    symbols = [r.canonical_symbol for r in results]
    assert "A1" not in symbols
    assert "A2" in symbols


def test_deactivate_missing_is_noop(nse) -> None:
    import uuid

    # Should not raise
    instruments_deactivate(uuid.uuid4())


def test_search_asset_class_filter(nfo) -> None:
    instruments_create(
        venue_code="NFO",
        canonical_symbol="NIFTY",
        asset_class="INDEX",
        instrument_kind="CASH",
    )
    instruments_create(
        venue_code="NFO",
        canonical_symbol="BANKNIFTY",
        asset_class="INDEX",
        instrument_kind="CASH",
    )
    instruments_create(
        venue_code="NFO",
        canonical_symbol="FINNIFTY",
        asset_class="INDEX",
        instrument_kind="CASH",
    )

    idx = instruments_search(venue_code="NFO", asset_class="INDEX")
    assert len(idx) == 3
    assert [r.canonical_symbol for r in idx] == [
        "BANKNIFTY",
        "FINNIFTY",
        "NIFTY",
    ]
