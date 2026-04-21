"""subscribe_by_instrument_ref resolves a ref and calls legacy subscribe.

The underlying `subscribe(symbol, exchange, mode, depth_level)` call
must match exactly what the legacy path would have produced for the
same (venue_code, canonical_symbol).
"""

from __future__ import annotations

from database.instruments_repo import (
    BrokerMapRow,
    broker_map_upsert_many,
    instruments_create,
    sync_run_start,
    venues_upsert,
)
from domain.enums import IdentifierType
from domain.instrument_ref import InstrumentRef


def test_subscribe_venue_symbol_delegates_to_legacy(
    adapter, instruments_db, reset_default_resolver
):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )

    result = adapter.subscribe_by_instrument_ref(
        InstrumentRef(venue_code="NSE", canonical_symbol="RELIANCE"),
        mode=2,
        depth_level=5,
    )
    assert result["status"] == "success"
    # subscribe() received exactly what the legacy caller would have sent.
    assert adapter.subscribe_calls == [("RELIANCE", "NSE", 2, 5)]
    # State map populated with the resolved instrument_id.
    assert adapter._subscribed_instrument_ids[("NSE", "RELIANCE")] == inst.instrument_id


def test_subscribe_by_id_ref(adapter, instruments_db, reset_default_resolver):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="INFY",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    adapter.subscribe_by_instrument_ref(InstrumentRef(instrument_id=inst.instrument_id))
    assert adapter.subscribe_calls == [("INFY", "NSE", 2, 5)]


def test_subscribe_by_broker_token(adapter, instruments_db, reset_default_resolver):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="HDFCBANK",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    r = sync_run_start("zerodha", "NSE")
    broker_map_upsert_many(
        "zerodha", "NSE",
        [BrokerMapRow("HDFCBANK", "341249", inst.instrument_id)],
        sync_version=r.sync_version,
    )

    adapter.subscribe_by_instrument_ref(
        InstrumentRef(
            identifier_type=IdentifierType.BROKER_TOKEN,
            identifier_value="341249",
            venue_code="NSE",
        )
    )
    # Delegated to legacy subscribe with the canonical symbol/venue.
    assert adapter.subscribe_calls == [("HDFCBANK", "NSE", 2, 5)]
    assert adapter._subscribed_instrument_ids[("NSE", "HDFCBANK")] == inst.instrument_id


def test_explicit_broker_code_overrides_adapter_attr(
    adapter, instruments_db, reset_default_resolver
):
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="SBIN",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    # Adapter default broker_code is "zerodha", but we pass "dhan" explicitly.
    adapter.subscribe_by_instrument_ref(
        InstrumentRef(venue_code="NSE", canonical_symbol="SBIN"),
        broker_code="dhan",
    )
    assert adapter._subscribed_instrument_ids[("NSE", "SBIN")] == inst.instrument_id
