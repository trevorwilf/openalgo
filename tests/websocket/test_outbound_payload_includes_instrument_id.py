"""Outbound tick / depth payloads additively include `instrument_id`
when WEBSOCKET_INSTRUMENT_V2 is on and the (exchange, symbol) pair was
tracked via subscribe_by_instrument_ref.
"""

from __future__ import annotations

from database.instruments_repo import (
    instruments_create,
    venues_upsert,
)
from domain.instrument_ref import InstrumentRef


def _subscribe(adapter, venue="NSE", symbol="RELIANCE"):
    adapter.subscribe_by_instrument_ref(
        InstrumentRef(venue_code=venue, canonical_symbol=symbol)
    )


def test_flag_on_enriches_payload(
    adapter, instruments_db, reset_default_resolver, monkeypatch
):
    monkeypatch.setenv("WEBSOCKET_INSTRUMENT_V2", "1")
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    inst = instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    _subscribe(adapter)

    tick = {"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2900.5, "volume": 1000}
    adapter.publish_market_data("NSE_RELIANCE_LTP", tick)

    topic, sent = adapter.published[0]
    assert topic == "NSE_RELIANCE_LTP"
    assert sent["ltp"] == 2900.5
    assert sent["volume"] == 1000
    assert sent["instrument_id"] == str(inst.instrument_id)
    # The caller's dict was not mutated.
    assert "instrument_id" not in tick


def test_flag_off_passes_through_unchanged(
    adapter, instruments_db, reset_default_resolver, monkeypatch
):
    monkeypatch.delenv("WEBSOCKET_INSTRUMENT_V2", raising=False)
    venues_upsert("NSE", market_family="IN_STOCK", timezone_name="Asia/Kolkata")
    instruments_create(
        venue_code="NSE",
        canonical_symbol="RELIANCE",
        asset_class="EQUITY",
        instrument_kind="CASH",
    )
    _subscribe(adapter)

    tick = {"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2900.5}
    adapter.publish_market_data("NSE_RELIANCE_LTP", tick)

    _, sent = adapter.published[0]
    assert sent == tick  # byte-identical
    assert "instrument_id" not in sent


def test_flag_on_untracked_symbol_passes_through(adapter, monkeypatch):
    """Flag on but the (exchange, symbol) was never subscribed via the
    new method — payload is untouched."""
    monkeypatch.setenv("WEBSOCKET_INSTRUMENT_V2", "1")
    tick = {"symbol": "INFY", "exchange": "NSE", "ltp": 1500}
    adapter.publish_market_data("NSE_INFY_LTP", tick)
    _, sent = adapter.published[0]
    assert "instrument_id" not in sent


def test_flag_on_missing_symbol_key_passes_through(adapter, monkeypatch):
    """An event dict without symbol/exchange keys is safe."""
    monkeypatch.setenv("WEBSOCKET_INSTRUMENT_V2", "1")
    evt = {"type": "connected"}
    adapter.publish_market_data("internal.status", evt)
    _, sent = adapter.published[0]
    assert sent == evt


def test_flag_on_non_dict_data_passes_through(adapter, monkeypatch):
    """A non-dict payload (list of ticks, etc.) is returned unchanged."""
    monkeypatch.setenv("WEBSOCKET_INSTRUMENT_V2", "1")
    evt = ["tick1", "tick2"]
    enriched = adapter._enrich_outbound_data(evt)
    assert enriched is evt
