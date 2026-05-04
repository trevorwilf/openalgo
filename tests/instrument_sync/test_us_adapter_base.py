"""T-26 (v7 Phase 7-bis) — sync adapter base reads from region plugin.

Asserts the new ``BaseInstrumentSyncAdapter`` /
``USBrokerSyncAdapterBase`` resolve ``venue_timezone`` and
``currency`` through the active region plugin instead of the
hard-coded ``"Asia/Kolkata"`` / ``"INR"`` / ``"America/New_York"``
/ ``"USD"`` literals that previously lived on the per-broker
adapter classes.
"""

from __future__ import annotations


def test_zerodha_resolves_through_india_region():
    from services.instrument_sync_adapters.zerodha_adapter import ZerodhaAdapter

    adapter = ZerodhaAdapter(csv_path="/tmp/dummy.csv")
    assert adapter.region_code == "india"
    assert adapter.venue_timezone == "Asia/Kolkata"
    assert adapter.currency == "INR"


def test_alpaca_resolves_through_us_region():
    from services.instrument_sync_adapters.alpaca_adapter import AlpacaAdapter

    adapter = AlpacaAdapter(json_path="/tmp/dummy.json")
    assert adapter.region_code == "us"
    assert adapter.venue_timezone == "America/New_York"
    assert adapter.currency == "USD"


def test_base_falls_back_to_india_when_region_missing():
    """When the configured ``region_code`` doesn't resolve to a
    loaded plugin, the base falls back to the documented India
    fallback constants. Lets boot-time test environments succeed."""
    from services.instrument_sync_adapters._base import BaseInstrumentSyncAdapter

    class _Test(BaseInstrumentSyncAdapter):
        broker_code = "test"
        region_code = "atlantis"  # nonexistent

    a = _Test()
    assert a.venue_timezone == "Asia/Kolkata"
    assert a.currency == "INR"
