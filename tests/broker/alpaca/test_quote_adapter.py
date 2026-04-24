"""AlpacaQuoteAdapter — mocked HTTP round-trip."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.quote_api import AlpacaQuoteAdapter
from domain.broker_market_data import AccountContext
from domain.errors import UnsupportedCapability


LATEST_QUOTE_PAYLOAD = {
    "symbol": "AAPL",
    "quote": {
        "t": "2026-04-23T14:30:00.123Z",
        "ax": "V",
        "ap": 175.02,
        "as": 200,
        "bx": "V",
        "bp": 175.00,
        "bs": 100,
        "x": "XNAS",
    },
}


def _auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _data_client(auth: AlpacaAuth) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/stocks/AAPL/quotes/latest":
            return httpx.Response(200, json=LATEST_QUOTE_PAYLOAD)
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


def test_unknown_venue_raises_unsupported():
    auth = _auth()
    adapter = AlpacaQuoteAdapter(auth=auth)
    with pytest.raises(UnsupportedCapability):
        adapter.get_quote(
            _FakeInstrument("RELIANCE", "NSE"),
            AccountContext(broker_code="alpaca"),
        )
