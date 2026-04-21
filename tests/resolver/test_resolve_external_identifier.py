"""Resolve by external identifier: ISIN, BROKER_TOKEN, BROKER_SYMBOL."""

from __future__ import annotations

import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    identifier_add,
    instruments_create,
    sync_run_start,
    venues_upsert,
)
from domain.enums import IdentifierType
from domain.instrument_ref import InstrumentRef
from services.instrument_resolver import InstrumentResolver, ResolverMiss


def test_resolve_by_isin_venue_agnostic(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    identifier_add(inst.instrument_id, "ISIN", "INE002A01018", venue_code="NSE")

    resolver = InstrumentResolver()
    result = resolver.resolve(
        InstrumentRef(
            identifier_type=IdentifierType.ISIN,
            identifier_value="INE002A01018",
        )
    )
    assert result.instrument_id == inst.instrument_id


def test_resolve_by_isin_across_venues_is_ambiguous(fresh_db) -> None:
    """Same ISIN shared by NSE and BSE instruments — without a
    venue_code narrower the resolver raises ResolverAmbiguous."""
    from services.instrument_resolver import ResolverAmbiguous

    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    venues_upsert("BSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    a = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    b = instruments_create(
        venue_code="BSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    identifier_add(a.instrument_id, "ISIN", "INE002A01018", venue_code="NSE")
    identifier_add(b.instrument_id, "ISIN", "INE002A01018", venue_code="BSE")

    resolver = InstrumentResolver()
    with pytest.raises(ResolverAmbiguous):
        resolver.resolve(
            InstrumentRef(
                identifier_type=IdentifierType.ISIN,
                identifier_value="INE002A01018",
            )
        )


def test_resolve_by_broker_token(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="HDFCBANK",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("HDFCBANK", "341249", inst.instrument_id)],
        sync_version=r.sync_version,
    )
    resolver = InstrumentResolver()
    result = resolver.resolve(
        InstrumentRef(
            identifier_type=IdentifierType.BROKER_TOKEN,
            identifier_value="341249",
            venue_code="NSE",
        ),
        broker_code="zerodha",
    )
    assert result.instrument_id == inst.instrument_id
    assert result.external_token == "341249"


def test_resolve_broker_token_without_venue_raises(fresh_db) -> None:
    resolver = InstrumentResolver()
    with pytest.raises(ResolverMiss, match="venue_code"):
        resolver.resolve(
            InstrumentRef(
                identifier_type=IdentifierType.BROKER_TOKEN,
                identifier_value="123",
            ),
            broker_code="zerodha",
        )


def test_resolve_by_broker_symbol(fresh_db) -> None:
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("INFY-EQ", "408065", inst.instrument_id)],
        sync_version=r.sync_version,
    )
    resolver = InstrumentResolver()
    result = resolver.resolve(
        InstrumentRef(
            identifier_type=IdentifierType.BROKER_SYMBOL,
            identifier_value="INFY-EQ",
            venue_code="NSE",
        ),
        broker_code="zerodha",
    )
    assert result.instrument_id == inst.instrument_id
    assert result.external_symbol == "INFY-EQ"


def test_resolve_by_unsupported_identifier_type_raises(fresh_db) -> None:
    resolver = InstrumentResolver()
    with pytest.raises(ResolverMiss, match="not supported"):
        resolver.resolve(
            InstrumentRef(
                identifier_type=IdentifierType.RIC,
                identifier_value="RELI.NS",
            )
        )


def test_resolve_isin_misses_cleanly(fresh_db) -> None:
    resolver = InstrumentResolver()
    with pytest.raises(ResolverMiss, match="ISIN"):
        resolver.resolve(
            InstrumentRef(
                identifier_type=IdentifierType.ISIN,
                identifier_value="INE999A99999",
            )
        )
