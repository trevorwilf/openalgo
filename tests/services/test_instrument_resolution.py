"""Tests for services.instrument_resolution.resolve_instrument.

Must prove:

- id / venue_symbol / external ref shapes all resolve
- broker_instrument_map enriches the result when present
- get_token is never called on any path
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from database import instruments_repo
from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)
from domain.instrument_ref import InstrumentRef
from services.instrument_resolution import resolve_instrument


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "resolution.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


def _seed(broker_code: str = "fake_us"):
    venues_upsert(
        "XNAS",
        market_family="US_STOCK",
        country_code="US",
        base_currency="USD",
        timezone_name="America/New_York",
    )
    venues_upsert(
        "NSE",
        market_family="IN_STOCK",
        country_code="IN",
        base_currency="INR",
        timezone_name="Asia/Kolkata",
    )
    aapl = instruments_create(
        venue_code="XNAS",
        canonical_symbol="AAPL",
        asset_class="EQUITY",
        instrument_kind="CASH",
        tick_size=Decimal("0.01"),
        quantity_precision=6,
        currency="USD",
    )
    rel = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
        tick_size=Decimal("0.05"),
        lot_size=1,
        quantity_precision=0,
        currency="INR",
    )
    broker_map_upsert_many(
        broker_code=broker_code,
        venue_code="XNAS",
        sync_version=1,
        rows=[
            BrokerMapRow(
                external_symbol="AAPL",
                external_token="FAKE-AAPL-TOKEN",
                instrument_id=aapl.instrument_id,
            )
        ],
    )
    return aapl.instrument_id, rel.instrument_id


def test_resolve_by_id_returns_populated_row(
    fresh_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_get_token(monkeypatch)
    aapl_id, _ = _seed()
    ref = InstrumentRef(instrument_id=aapl_id)
    r = resolve_instrument(ref, broker_code="fake_us")
    assert r is not None
    assert r.venue_code == "XNAS"
    assert r.canonical_symbol == "AAPL"
    assert r.currency == "USD"
    assert r.supports_fractional is True
    assert r.broker_native_symbol == "AAPL"
    assert r.broker_native_token == "FAKE-AAPL-TOKEN"


def test_resolve_by_venue_symbol_without_broker_map(
    fresh_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_get_token(monkeypatch)
    _seed()
    # Indian equity — no fake_us broker map.
    ref = InstrumentRef(venue_code="NSE", canonical_symbol="RELIANCE")
    r = resolve_instrument(ref, broker_code="fake_us")
    assert r is not None
    assert r.venue_code == "NSE"
    assert r.canonical_symbol == "RELIANCE"
    assert r.broker_native_symbol is None


def test_resolve_missing_returns_none(
    fresh_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_get_token(monkeypatch)
    _seed()
    ref = InstrumentRef(venue_code="XNAS", canonical_symbol="NOSUCH")
    assert resolve_instrument(ref, broker_code="fake_us") is None


def _forbid_get_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any call to legacy get_token throws — proves we never depend on it."""
    def _raise(*args, **kwargs):
        raise AssertionError("resolve_instrument must not call get_token")

    monkeypatch.setattr("database.token_db.get_token", _raise)
