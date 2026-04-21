"""With WEBSOCKET_INSTRUMENT_V2 off, _enrich_outbound_data is a no-op
for every shape of tick/depth payload we expect to see. This is the
byte-identical parity guarantee.
"""

from __future__ import annotations

import pytest


PAYLOADS = [
    {"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2900.5, "volume": 1000},
    {
        "symbol": "NIFTY28MAR2422500CE",
        "exchange": "NFO",
        "ltp": 100.5,
        "oi": 50000,
        "bid": 100.0,
        "ask": 101.0,
    },
    {
        "symbol": "BTCUSDT",
        "exchange": "CRYPTO",
        "bid": 45000.0,
        "ask": 45001.0,
        "volume": 0.5,
    },
    {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "bids": [{"price": 2900, "size": 100}],
        "asks": [{"price": 2900.5, "size": 50}],
    },
    {"type": "heartbeat", "ts": 1700000000},
    {"type": "status", "message": "connected"},
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_flag_off_payload_byte_identical(adapter, monkeypatch, payload):
    monkeypatch.delenv("WEBSOCKET_INSTRUMENT_V2", raising=False)
    # Even with a tracked instrument_id, flag-off must NOT enrich.
    from uuid import uuid4
    adapter._subscribed_instrument_ids[
        (payload.get("exchange", "NSE"), payload.get("symbol", "RELIANCE"))
    ] = uuid4()

    enriched = adapter._enrich_outbound_data(payload)
    # Must be the exact same object (no copy), not merely equal.
    assert enriched is payload
