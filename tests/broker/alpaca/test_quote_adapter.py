"""AlpacaQuoteAdapter — mocked HTTP round-trip."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
from domain.broker_market_data import AccountContext
from domain.errors import UnsupportedCapability


# Snapshot endpoint shape — what /v2/stocks/{symbol}/snapshot
# actually returns. latestTrade is what the adapter reads for
# ``last`` (the previous /quotes/latest endpoint omitted last-trade,
# so the adapter incorrectly fell back to ask price).
SNAPSHOT_PAYLOAD = {
    "symbol": "AAPL",
    "latestTrade": {
        "t": "2026-04-23T14:30:00.123Z",
        "p": 175.01,
        "s": 100,
        "x": "V",
    },
    "latestQuote": {
        "t": "2026-04-23T14:30:00.150Z",
        "ax": "V",
        "ap": 175.02,
        "as": 200,
        "bx": "V",
        "bp": 175.00,
        "bs": 100,
        "x": "XNAS",
    },
    "minuteBar": {
        "t": "2026-04-23T14:30:00Z",
        "o": 175.00, "h": 175.05, "l": 174.95, "c": 175.01, "v": 1234,
    },
    "dailyBar": {
        "t": "2026-04-23T00:00:00Z",
        "o": 174.50, "h": 175.10, "l": 174.20, "c": 175.01, "v": 12345678,
    },
    "prevDailyBar": {
        "t": "2026-04-22T00:00:00Z",
        "o": 173.00, "h": 174.80, "l": 172.90, "c": 174.55, "v": 11111111,
    },
}


def _auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _data_client(auth: AlpacaAuth, payload: dict | None = None) -> httpx.Client:
    body = payload if payload is not None else SNAPSHOT_PAYLOAD

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/stocks/AAPL/snapshot":
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.Client(
        base_url=auth.data_base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


class _FakeInstrument:
    def __init__(self, symbol: str, venue: str, fractional: bool = True) -> None:
        self.instrument_id = "00000000-0000-0000-0000-000000000001"
        self.venue_code = venue
        self.canonical_symbol = symbol
        self.broker_native_symbol = symbol
        self.supports_fractional = fractional
        self.currency = "USD"


def test_get_quote_normalizes_payload():
    auth = _auth()
    with _data_client(auth) as c:
        adapter = AlpacaQuoteAdapter(auth=auth, client=c)
        q = adapter.get_quote(
            _FakeInstrument("AAPL", "XNAS"),
            AccountContext(broker_code="alpaca"),
        )
    assert q.canonical_symbol == "AAPL"
    assert q.venue_code == "XNAS"
    assert q.bid == Decimal("175.00")
    assert q.ask == Decimal("175.02")
    assert q.bid_size == Decimal("100")
    assert q.ask_size == Decimal("200")
    assert q.currency.value == "USD"
    assert q.timestamp is not None
    assert q.timestamp.tzinfo is not None


def test_get_quote_last_is_real_trade_price_not_ask():
    """Regression: previously ``last`` fell back to ask price because
    the /quotes/latest endpoint omitted last-trade. The snapshot
    endpoint provides ``latestTrade.p`` directly.
    """
    auth = _auth()
    with _data_client(auth) as c:
        adapter = AlpacaQuoteAdapter(auth=auth, client=c)
        q = adapter.get_quote(
            _FakeInstrument("AAPL", "XNAS"),
            AccountContext(broker_code="alpaca"),
        )
    assert q.last == Decimal("175.01")
    # And it's NOT the ask price.
    assert q.last != q.ask


def test_get_quote_metadata_includes_daily_ohlcv():
    """OHLCV from the daily bar must reach the v1 bridge so /quotes,
    /multiquotes, /depth render real high/low/open/prev_close
    instead of stamping ``last`` into every field.
    """
    auth = _auth()
    with _data_client(auth) as c:
        adapter = AlpacaQuoteAdapter(auth=auth, client=c)
        q = adapter.get_quote(
            _FakeInstrument("AAPL", "XNAS"),
            AccountContext(broker_code="alpaca"),
        )
    assert q.metadata["open"] == Decimal("174.50")
    assert q.metadata["high"] == Decimal("175.10")
    assert q.metadata["low"] == Decimal("174.20")
    assert q.metadata["close"] == Decimal("175.01")
    assert q.metadata["volume"] == Decimal("12345678")
    assert q.metadata["prev_close"] == Decimal("174.55")


def test_get_quote_falls_back_to_midpoint_when_no_trade():
    """For thinly-traded symbols outside RTH the snapshot may have
    no latestTrade. Fall back to bid+ask midpoint rather than
    picking the ask side.
    """
    payload = dict(SNAPSHOT_PAYLOAD)
    payload["latestTrade"] = None
    auth = _auth()
    with _data_client(auth, payload=payload) as c:
        adapter = AlpacaQuoteAdapter(auth=auth, client=c)
        q = adapter.get_quote(
            _FakeInstrument("AAPL", "XNAS"),
            AccountContext(broker_code="alpaca"),
        )
    # Midpoint of 175.00 / 175.02 = 175.01
    assert q.last == Decimal("175.01")


def test_unknown_venue_raises_unsupported():
    auth = _auth()
    adapter = AlpacaQuoteAdapter(auth=auth)
    with pytest.raises(UnsupportedCapability):
        adapter.get_quote(
            _FakeInstrument("RELIANCE", "NSE"),
            AccountContext(broker_code="alpaca"),
        )
