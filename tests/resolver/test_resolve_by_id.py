"""Resolve by canonical instrument_id (Phase 2a UUID)."""

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
from services.instrument_resolver import (
    InstrumentResolver,
    ResolverMiss,
)


def test_resolve_by_id_hits(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instrument = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    resolver = InstrumentResolver()
    result = resolver.resolve(InstrumentRef(instrument_id=instrument.instrument_id))
    assert result.instrument_id == instrument.instrument_id
    assert result.venue_code == "NSE"
    assert result.canonical_symbol == "RELIANCE"
    assert result.legacy_fallback is False


def test_resolve_by_id_populates_broker_fields_when_map_exists(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instrument = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("INFY", "408065", instrument.instrument_id)],
        sync_version=r.sync_version,
    )

    resolver = InstrumentResolver()
    result = resolver.resolve(
        InstrumentRef(instrument_id=instrument.instrument_id),
        broker_code="zerodha",
    )
    assert result.broker_code == "zerodha"
    assert result.external_token == "408065"
    assert result.external_symbol == "INFY"


def test_resolve_by_id_missing_raises_miss(fresh_db) -> None:
    import uuid
    resolver = InstrumentResolver()
    with pytest.raises(ResolverMiss, match="not in universe"):
        resolver.resolve(InstrumentRef(instrument_id=uuid.uuid4()))
