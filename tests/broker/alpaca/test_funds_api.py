"""broker/alpaca/api/funds.py — get_margin_data."""

from __future__ import annotations

import json

import httpx

from broker.alpaca.api.auth_api import (
    DATA_BASE_URL,
    PAPER_BASE_URL,
)
from broker.alpaca.api.funds import get_margin_data


def _token() -> str:
    return json.dumps(
        {
            "api_key": "ak",
            "api_secret": "sk",
            "is_paper": True,
            "base_url": PAPER_BASE_URL,
            "data_base_url": DATA_BASE_URL,
        }
    )


def _patch_v2_account(
    monkeypatch,
    body: dict,
    status: int = 200,
    positions: list[dict] | None = None,
) -> None:
    """Patch httpx.Client.get to serve both /v2/account and /v2/positions.

    The funds module now also fetches /v2/positions to back out the
    realized intraday P&L component. Tests opt in to a positions
    response by passing a ``positions`` list; the default empty list
    matches the no-open-positions case.
    """
    pos_body = list(positions or [])

    def _fake_get(self, url, *args, **kwargs):
        if url.endswith("/v2/positions"):
            return httpx.Response(
                200,
                json=pos_body,
                request=httpx.Request("GET", f"{PAPER_BASE_URL}{url}"),
            )
        return httpx.Response(
            status,
            json=body,
            request=httpx.Request("GET", f"{PAPER_BASE_URL}{url}"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)


def test_get_margin_data_returns_widget_shape(monkeypatch):
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "100000",
            "equity": "100000",
            "last_equity": "100000",
            "long_market_value": "0",
            "short_market_value": "0",
        },
    )
    funds = get_margin_data(_token())
    assert funds == {
        "availablecash": "100000.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }


def test_get_margin_data_with_open_positions(monkeypatch):
    """1500 of intraday P&L, all of it sitting unrealized in an open
    position → m2munrealized=1500, m2mrealized=0."""
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "50000",
            "equity": "100000",
            "last_equity": "98500",      # +1500 intraday
            "long_market_value": "50000",
            "short_market_value": "0",
        },
        positions=[{"symbol": "AAPL", "unrealized_intraday_pl": "1500"}],
    )
    funds = get_margin_data(_token())
    assert funds["availablecash"] == "50000.00"
    assert funds["m2munrealized"] == "1500.00"
    assert funds["m2mrealized"] == "0.00"
    assert funds["utiliseddebits"] == "50000.00"


def test_get_margin_data_realized_when_position_closed(monkeypatch):
    """1500 of intraday P&L with no open positions → all realized."""
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "100000",
            "equity": "100000",
            "last_equity": "98500",
            "long_market_value": "0",
            "short_market_value": "0",
        },
        positions=[],
    )
    funds = get_margin_data(_token())
    assert funds["m2munrealized"] == "0.00"
    assert funds["m2mrealized"] == "1500.00"


def test_get_margin_data_mixed_realized_and_unrealized(monkeypatch):
    """2000 intraday P&L = 1200 unrealized (open MSFT) + 800 realized
    (closed AAPL trade)."""
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "85000",
            "equity": "102000",
            "last_equity": "100000",
            "long_market_value": "17000",
            "short_market_value": "0",
        },
        positions=[{"symbol": "MSFT", "unrealized_intraday_pl": "1200"}],
    )
    funds = get_margin_data(_token())
    assert funds["m2munrealized"] == "1200.00"
    assert funds["m2mrealized"] == "800.00"


def test_get_margin_data_positions_endpoint_failure_falls_back(monkeypatch):
    """If /v2/positions fails, m2mrealized falls back to 0 and the
    widget still renders rather than dropping entirely."""
    def _fake_get(self, url, *args, **kwargs):
        if url.endswith("/v2/positions"):
            raise httpx.ConnectError("positions unavailable")
        return httpx.Response(
            200,
            json={
                "cash": "50000",
                "equity": "100000",
                "last_equity": "98500",
                "long_market_value": "50000",
                "short_market_value": "0",
            },
            request=httpx.Request("GET", f"{PAPER_BASE_URL}{url}"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)
    funds = get_margin_data(_token())
    assert funds["availablecash"] == "50000.00"
    # No position data → unrealized=0, all of intraday counts as realized
    assert funds["m2munrealized"] == "0.00"
    assert funds["m2mrealized"] == "1500.00"


def test_get_margin_data_handles_invalid_token():
    """Bad token → empty dict + log; never raises."""
    funds = get_margin_data("not-json")
    assert funds == {}


def test_get_margin_data_handles_http_error(monkeypatch):
    def _fake_get(self, url, *args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "get", _fake_get)
    funds = get_margin_data(_token())
    assert funds == {}


def test_get_margin_data_with_short_position_uses_gross_exposure(monkeypatch):
    """Regression: Alpaca returns short_market_value as a NEGATIVE
    number (value owed on shorts). The funds widget's
    ``utiliseddebits`` should reflect gross exposure
    (long + |short|), not net (long + short), otherwise short
    positions hide the margin they actually consume.

    Long $10k AAPL + short $5k MSFT →
        long_mv = 10000, short_mv = -5000
        gross (correct):   utiliseddebits = "15000.00"
        net   (regressed): utiliseddebits = "5000.00"
    """
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "85000",
            "equity": "100000",
            "last_equity": "100000",
            "long_market_value": "10000",
            "short_market_value": "-5000",
        },
    )
    funds = get_margin_data(_token())
    assert funds["utiliseddebits"] == "15000.00"


def test_get_margin_data_short_only_position(monkeypatch):
    """A pure short book still consumes margin equal to the absolute
    short exposure — utiliseddebits must not collapse to 0.
    """
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "100000",
            "equity": "100000",
            "last_equity": "100000",
            "long_market_value": "0",
            "short_market_value": "-7500",
        },
    )
    funds = get_margin_data(_token())
    assert funds["utiliseddebits"] == "7500.00"


def test_get_margin_data_floors_negative_used_at_zero(monkeypatch):
    """Cash > equity (e.g. transfer pending) → utiliseddebits = 0."""
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "100000",
            "equity": "100000",
            "last_equity": "100000",
            "long_market_value": "0",
            "short_market_value": "0",
        },
    )
    funds = get_margin_data(_token())
    assert funds["utiliseddebits"] == "0.00"
