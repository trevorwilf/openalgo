"""Resolve by (venue_code, canonical_symbol). Covers the collision
case: same symbol on two different venues — resolver must pick the
right one given venue_code.
"""

from __future__ import annotations

import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    sync_run_start,
    venues_upsert,
)
from domain.instrument_ref import InstrumentRef
from services.instrument_resolver import InstrumentResolver, ResolverMiss


def test_resolve_venue_symbol_hits(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="SBIN",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver()
    result = resolver.resolve(InstrumentRef(venue_code="NSE", canonical_symbol="SBIN"))
    assert result.instrument_id == inst.instrument_id
    assert result.venue_code == "NSE"
    assert result.legacy_fallback is False


def test_cross_venue_collision_same_symbol(fresh_db) -> None:
    """The canonical symbol "INFY" exists on both NSE and a synthetic
    US venue. The resolver must return the correct instrument based on
    the venue_code supplied in the ref.
    """
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("XNAS", market_family="US_STOCK", timezone_name="America/New_York")

    infy_nse = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    infy_us = instruments_create(
        venue_code="XNAS",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    assert infy_nse.instrument_id != infy_us.instrument_id

    resolver = InstrumentResolver()
    nse = resolver.resolve(InstrumentRef(venue_code="NSE", canonical_symbol="INFY"))
    us = resolver.resolve(InstrumentRef(venue_code="XNAS", canonical_symbol="INFY"))
    assert nse.instrument_id == infy_nse.instrument_id
    assert us.instrument_id == infy_us.instrument_id


def test_resolve_venue_symbol_populates_broker_fields(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="TATAMOTORS",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("TATAMOTORS", "884737", inst.instrument_id)],
        sync_version=r.sync_version,
    )
    resolver = InstrumentResolver()
    result = resolver.resolve(
        InstrumentRef(venue_code="NSE", canonical_symbol="TATAMOTORS"),
        broker_code="zerodha",
    )
    assert result.external_token == "884737"
    assert result.broker_code == "zerodha"
    assert result.legacy_fallback is False


def test_resolve_venue_symbol_no_legacy_no_match_raises(fresh_db) -> None:
    resolver = InstrumentResolver()  # no legacy_token_lookup wired
    with pytest.raises(ResolverMiss):
        resolver.resolve(InstrumentRef(venue_code="NSE", canonical_symbol="GHOST"))
