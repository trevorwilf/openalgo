"""Zerodha adapter + runner end-to-end against a fixture CSV."""

from __future__ import annotations

from pathlib import Path

from database.instruments_repo import (
    broker_map_lookup_by_symbol,
    broker_map_lookup_by_token,
    instruments_get_by_venue_symbol,
    sync_run_latest,
    venues_list,
)
from services.instrument_sync_adapters.zerodha_adapter import ZerodhaAdapter
from services.instrument_sync_service import InstrumentSyncRunner


def test_zerodha_full_run(fresh_db, zerodha_fixture: Path) -> None:
    adapter = ZerodhaAdapter(csv_path=zerodha_fixture)
    result = InstrumentSyncRunner().run(adapter)

    # The fixture contains 20 rows; one has an unknown segment that the
    # adapter filters out — expect 19 live rows.
    assert result.status == "success"
    assert result.instrument_count == 19
    assert result.new_count == 19
    assert result.updated_count == 0
    assert result.retired_count == 0
    assert result.checksum is not None

    # Venues upserted
    venue_codes = {v.venue_code for v in venues_list()}
    assert {"NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "NSE_INDEX", "BSE_INDEX"} <= venue_codes

    # Spot check a cash row
    reliance_nse = instruments_get_by_venue_symbol("NSE", "RELIANCE")
    assert reliance_nse is not None
    assert reliance_nse.asset_class == "EQUITY"
    assert reliance_nse.currency == "INR"

    # Spot check broker-map lookup
    row = broker_map_lookup_by_symbol("zerodha", "NSE", "RELIANCE")
    assert row is not None
    assert row.instrument_id == reliance_nse.instrument_id
    assert row.external_token == "738561"

    token_row = broker_map_lookup_by_token("zerodha", "NSE", "738561")
    assert token_row is not None
    assert token_row.instrument_id == reliance_nse.instrument_id

    # Check the option row preserves strike + option_right + expiry
    from database.instruments_repo import Instrument, session_scope
    from sqlalchemy import select

    with session_scope() as s:
        ce = s.scalar(
            select(Instrument).where(
                Instrument.venue_code == "NFO",
                Instrument.canonical_symbol == "NIFTY24APR2422500CE",
            )
        )
    assert ce is not None
    assert ce.asset_class == "OPTION"
    assert ce.option_right == "CALL"
    assert ce.expiration_at is not None

    # Sync-run marked success with expected version
    latest = sync_run_latest("zerodha")
    assert latest is not None
    assert latest.status == "success"
    assert latest.sync_version == 1
    assert latest.instrument_count == 19


def test_zerodha_idempotent_second_run_updates_not_inserts(
    fresh_db, zerodha_fixture: Path
) -> None:
    adapter = ZerodhaAdapter(csv_path=zerodha_fixture)
    InstrumentSyncRunner().run(adapter)
    result2 = InstrumentSyncRunner().run(adapter)

    assert result2.status == "success"
    assert result2.instrument_count == 19
    # Second run finds every row already present → no inserts, only updates.
    assert result2.new_count == 0
    assert result2.updated_count == 19
    # Nothing retired because every row was re-seen.
    assert result2.retired_count == 0


def test_zerodha_unknown_segment_row_is_skipped(
    fresh_db, zerodha_fixture: Path
) -> None:
    """The fixture has one row with segment=MYSTERY_SEGMENT. It must be
    silently skipped — the adapter logs at debug, runner continues."""
    adapter = ZerodhaAdapter(csv_path=zerodha_fixture)
    result = InstrumentSyncRunner().run(adapter)
    # 20 rows in fixture, 1 skipped, 19 stored.
    assert result.instrument_count == 19


def test_zerodha_identifiers_recorded(fresh_db, zerodha_fixture: Path) -> None:
    InstrumentSyncRunner().run(ZerodhaAdapter(csv_path=zerodha_fixture))
    from database.instruments_repo import identifier_resolve

    # Broker token recorded with narrowing keys
    matches = identifier_resolve(
        "BROKER_TOKEN", "738561", broker_code="zerodha", venue_code="NSE"
    )
    assert len(matches) == 1

    # Venue symbol recorded venue-agnostic-broker (broker_code None)
    venue_matches = identifier_resolve(
        "VENUE_SYMBOL", "RELIANCE", broker_code=None, venue_code="NSE"
    )
    assert len(venue_matches) == 1
