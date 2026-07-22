"""AlpacaBarAdapter — mocked HTTP round-trip."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

import broker.alpaca.api.bar_api as bar_api
from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.bar_api import AlpacaBarAdapter
from domain.broker_market_data import AccountContext, NormalizedBarRequest
from domain.errors import UnsupportedCapability


BARS_PAYLOAD = {
    "bars": {
        "AAPL": [
            {
                "t": "2026-04-23T14:30:00Z",
                "o": 175.0,
                "h": 175.5,
                "l": 174.9,
                "c": 175.3,
                "v": 12345,
            },
            {
                "t": "2026-04-23T14:31:00Z",
                "o": 175.3,
                "h": 175.4,
                "l": 175.1,
                "c": 175.2,
                "v": 6789,
            },
        ]
    },
    "next_page_token": None,
}


def _auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _data_client(auth: AlpacaAuth) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/stocks/bars":
            return httpx.Response(200, json=BARS_PAYLOAD)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.Client(
        base_url=auth.data_base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


class _FakeInstrument:
    def __init__(self) -> None:
        self.instrument_id = "00000000-0000-0000-0000-000000000001"
        self.venue_code = "XNAS"
        self.canonical_symbol = "AAPL"
        self.broker_native_symbol = "AAPL"


def test_get_bars_1m_returns_two_rows():
    auth = _auth()
    with _data_client(auth) as c:
        adapter = AlpacaBarAdapter(auth=auth, client=c)
        bars = adapter.get_bars(
            _FakeInstrument(),
            NormalizedBarRequest(
                interval="1m",
                start=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
                end=datetime(2026, 4, 23, 15, 0, tzinfo=timezone.utc),
            ),
            AccountContext(broker_code="alpaca"),
        )
    assert len(bars) == 2
    assert bars[0].open == Decimal("175.0")
    assert bars[0].close == Decimal("175.3")
    assert bars[1].volume == Decimal("6789")


def test_get_bars_follows_next_page_token():
    """Regression: bar adapter used to request a single page (limit=10000)
    and ignore ``next_page_token``, silently truncating any historical
    request that overflowed one page. Verify the loop chases the token
    and concatenates rows.
    """
    auth = _auth()

    page_one = {
        "bars": {
            "AAPL": [
                {
                    "t": "2026-04-23T14:30:00Z",
                    "o": 175.0, "h": 175.5, "l": 174.9, "c": 175.3, "v": 1,
                },
                {
                    "t": "2026-04-23T14:31:00Z",
                    "o": 175.3, "h": 175.4, "l": 175.1, "c": 175.2, "v": 2,
                },
            ]
        },
        "next_page_token": "page-2-token",
    }
    page_two = {
        "bars": {
            "AAPL": [
                {
                    "t": "2026-04-23T14:32:00Z",
                    "o": 175.2, "h": 175.6, "l": 175.0, "c": 175.5, "v": 3,
                },
            ]
        },
        "next_page_token": None,
    }

    seen_tokens: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/v2/stocks/bars":
            return httpx.Response(404, json={"message": "not found"})
        token = req.url.params.get("page_token")
        seen_tokens.append(token)
        return httpx.Response(200, json=page_two if token == "page-2-token" else page_one)

    with httpx.Client(
        base_url=auth.data_base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    ) as c:
        adapter = AlpacaBarAdapter(auth=auth, client=c)
        bars = adapter.get_bars(
            _FakeInstrument(),
            NormalizedBarRequest(
                interval="1m",
                start=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
                end=datetime(2026, 4, 23, 15, 0, tzinfo=timezone.utc),
            ),
            AccountContext(broker_code="alpaca"),
        )

    assert [t for t in seen_tokens] == [None, "page-2-token"]
    assert len(bars) == 3
    assert bars[2].volume == Decimal("3")


def test_get_bars_does_not_loop_when_no_next_page_token():
    """Single-page response with token=None must terminate after one
    request — no spurious second call.
    """
    auth = _auth()
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/v2/stocks/bars":
            return httpx.Response(404, json={"message": "not found"})
        call_count["n"] += 1
        return httpx.Response(200, json=BARS_PAYLOAD)

    with httpx.Client(
        base_url=auth.data_base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    ) as c:
        adapter = AlpacaBarAdapter(auth=auth, client=c)
        adapter.get_bars(
            _FakeInstrument(),
            NormalizedBarRequest(
                interval="1m",
                start=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
                end=datetime(2026, 4, 23, 15, 0, tzinfo=timezone.utc),
            ),
            AccountContext(broker_code="alpaca"),
        )
    assert call_count["n"] == 1


def test_unknown_interval_raises_unsupported():
    auth = _auth()
    adapter = AlpacaBarAdapter(auth=auth)
    with pytest.raises(UnsupportedCapability):
        adapter.get_bars(
            _FakeInstrument(),
            NormalizedBarRequest(
                interval="17s",
                start=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
                end=datetime(2026, 4, 23, 15, 0, tzinfo=timezone.utc),
            ),
            AccountContext(broker_code="alpaca"),
        )


def test_default_adapter_reuses_one_client_pool(monkeypatch):
    """Regression: the promoted singleton must not build an SSL/client
    stack for every symbol request.
    """
    created: list[object] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.closed = False
            self.calls = 0
            created.append(self)

        def get(self, _url, **_kwargs):
            self.calls += 1
            return httpx.Response(
                200,
                json=BARS_PAYLOAD,
                request=httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars"),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(bar_api.httpx, "Client", FakeClient)
    adapter = AlpacaBarAdapter(auth=_auth())
    request = NormalizedBarRequest(
        interval="1m",
        start=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        end=datetime(2026, 4, 23, 15, 0, tzinfo=timezone.utc),
    )

    adapter.get_bars(_FakeInstrument(), request, AccountContext(broker_code="alpaca"))
    adapter.get_bars(_FakeInstrument(), request, AccountContext(broker_code="alpaca"))

    assert len(created) == 1
    assert created[0].calls == 2
    adapter.close()
    assert created[0].closed is True
