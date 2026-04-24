"""Alpaca /v2/account and /v2/positions -> NormalizedBalance / NormalizedPosition.

Mocks the httpx client via a MockTransport so no real network call is
made. Reuses the fake paper sandbox shape from Alpaca docs.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from broker.alpaca.api.account_api import (
    get_account,
    get_account_snapshot,
    get_positions,
)
from broker.alpaca.api.auth_api import AlpacaAuth, PAPER_BASE_URL


PAPER_ACCOUNT = {
    "id": "acct-uuid-1",
    "account_number": "PA0123456",
    "status": "ACTIVE",
    "currency": "USD",
    "cash": "50000.00",
    "equity": "51234.56",
    "buying_power": "100000.00",
    "pattern_day_trader": False,
}

PAPER_POSITIONS = [
    {
        "asset_id": "asset-uuid-aapl",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "asset_class": "us_equity",
        "qty": "10",
        "side": "long",
        "avg_entry_price": "170.25",
        "current_price": "175.00",
        "unrealized_pl": "47.50",
    },
    {
        "asset_id": "asset-uuid-tsla",
        "symbol": "TSLA",
        "exchange": "XNAS",
        "asset_class": "us_equity",
        "qty": "0.5",
        "side": "long",
        "avg_entry_price": "200.00",
        "current_price": "202.10",
        "unrealized_pl": "1.05",
    },
]


def _mock_transport() -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/account":
            return httpx.Response(200, json=PAPER_ACCOUNT)
        if req.url.path == "/v2/positions":
            return httpx.Response(200, json=PAPER_POSITIONS)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


def _client(auth: AlpacaAuth) -> httpx.Client:
    return httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=_mock_transport(),
    )


@pytest.fixture
def paper_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url="https://data.alpaca.markets",
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def test_get_account_returns_normalized_balance(paper_auth):
    with _client(paper_auth) as c:
        bal = get_account(paper_auth, client=c)
    assert str(bal.available.amount) == "50000.00"
    assert str(bal.total.amount) == "51234.56"
    assert bal.available.currency.value == "USD"
    assert bal.extra["buying_power"] == "100000.00"
    assert bal.extra["account_id"] == "acct-uuid-1"


def test_get_positions_returns_list_with_fractional(paper_auth):
    with _client(paper_auth) as c:
        positions = get_positions(paper_auth, client=c)
    assert len(positions) == 2
    aapl = positions[0]
    assert aapl.instrument.canonical_symbol == "AAPL"
    assert aapl.instrument.venue_code == "XNAS"
    assert aapl.quantity == Decimal("10")
    assert aapl.quantity_unit.value == "WHOLE"
    tsla = positions[1]
    assert tsla.quantity == Decimal("0.5")
    assert tsla.quantity_unit.value == "FRACTIONAL"


def test_snapshot_combines_balance_and_positions(paper_auth):
    with _client(paper_auth) as c:
        snap = get_account_snapshot(paper_auth, client=c)
    assert snap.account_id == "acct-uuid-1"
    assert snap.currency.value == "USD"
    assert len(snap.positions) == 2
