"""Broker-instrument map: bulk upsert, lookup, sync-version progression, soft prune."""

from __future__ import annotations

from datetime import datetime

import pytest

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_lookup_by_symbol,
    broker_map_lookup_by_token,
    broker_map_prune_below_version,
    broker_map_upsert_many,
    instruments_create,
    venues_upsert,
)


@pytest.fixture
def nse_instruments(fresh_db):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    reliance = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    infy = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    return {"RELIANCE": reliance, "INFY": infy}


def test_bulk_upsert_inserts_rows(nse_instruments) -> None:
    count = broker_map_upsert_many(
        "zerodha",
        "NSE",
        [
            BrokerMapRow("RELIANCE-EQ", "738561", nse_instruments["RELIANCE"].instrument_id),
            BrokerMapRow("INFY-EQ", "408065", nse_instruments["INFY"].instrument_id),
        ],
        sync_version=1,
    )
    assert count == 2

    row = broker_map_lookup_by_symbol("zerodha", "NSE", "RELIANCE-EQ")
    assert row is not None
    assert row.sync_version == 1
    assert row.instrument_id == nse_instruments["RELIANCE"].instrument_id


def test_bulk_upsert_updates_existing(nse_instruments) -> None:
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("RELIANCE-EQ", "738561", nse_instruments["RELIANCE"].instrument_id)],
        sync_version=1,
    )
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        # Same external_symbol, new token
        [BrokerMapRow("RELIANCE-EQ", "000001", nse_instruments["RELIANCE"].instrument_id)],
        sync_version=2,
    )
    row = broker_map_lookup_by_symbol("zerodha", "NSE", "RELIANCE-EQ")
    assert row is not None
    assert row.sync_version == 2
    assert row.external_token == "000001"


def test_empty_bulk_upsert_returns_zero(nse_instruments) -> None:
    assert broker_map_upsert_many("zerodha", "NSE", [], sync_version=1) == 0


def test_lookup_by_token(nse_instruments) -> None:
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("INFY-EQ", "408065", nse_instruments["INFY"].instrument_id)],
        sync_version=1,
    )
    row = broker_map_lookup_by_token("zerodha", "NSE", "408065")
    assert row is not None
    assert row.instrument_id == nse_instruments["INFY"].instrument_id


def test_lookup_miss_returns_none(nse_instruments) -> None:
    assert broker_map_lookup_by_symbol("zerodha", "NSE", "DOES_NOT_EXIST") is None
    assert broker_map_lookup_by_token("zerodha", "NSE", "DOES_NOT_EXIST") is None


def test_soft_prune_does_not_delete(nse_instruments) -> None:
    """Rows below the cutoff version are soft-retired (last_seen_at
    stamped to epoch). They remain in the table."""
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [
            BrokerMapRow("RELIANCE-EQ", "738561", nse_instruments["RELIANCE"].instrument_id),
            BrokerMapRow("INFY-EQ", "408065", nse_instruments["INFY"].instrument_id),
        ],
        sync_version=1,
    )
    # Second sync sees only RELIANCE — so INFY is "stale" at version 2.
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("RELIANCE-EQ", "738561", nse_instruments["RELIANCE"].instrument_id)],
        sync_version=2,
    )
    pruned = broker_map_prune_below_version("zerodha", "NSE", min_sync_version=2)
    assert pruned == 1

    # INFY row still there, but last_seen_at stamped epoch.
    row = broker_map_lookup_by_symbol("zerodha", "NSE", "INFY-EQ")
    assert row is not None
    assert row.sync_version == 1
    assert row.last_seen_at == datetime.fromtimestamp(0)


def test_prune_no_rows_to_prune(nse_instruments) -> None:
    broker_map_upsert_many(
        "zerodha",
        "NSE",
        [BrokerMapRow("RELIANCE-EQ", "738561", nse_instruments["RELIANCE"].instrument_id)],
        sync_version=1,
    )
    # Cutoff at 1 → nothing below; returns 0.
    assert broker_map_prune_below_version("zerodha", "NSE", min_sync_version=1) == 0


def test_two_brokers_coexist(nse_instruments) -> None:
    """Two brokers' maps must be isolated by broker_code."""
    rid = nse_instruments["RELIANCE"].instrument_id
    broker_map_upsert_many(
        "zerodha", "NSE", [BrokerMapRow("RELIANCE-EQ", "738561", rid)], sync_version=1
    )
    broker_map_upsert_many(
        "dhan", "NSE", [BrokerMapRow("RELIANCE", "2885", rid)], sync_version=1
    )
    assert (
        broker_map_lookup_by_symbol("zerodha", "NSE", "RELIANCE-EQ").external_token
        == "738561"
    )
    assert (
        broker_map_lookup_by_symbol("dhan", "NSE", "RELIANCE").external_token == "2885"
    )
