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


def _patch_v2_account(monkeypatch, body: dict, status: int = 200) -> None:
    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            status,
            json=body,
            request=httpx.Request("GET", f"{PAPER_BASE_URL}/v2/account"),
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
    _patch_v2_account(
        monkeypatch,
        {
            "cash": "50000",
            "equity": "100000",
            "last_equity": "98500",      # +1500 intraday
            "long_market_value": "50000",
            "short_market_value": "0",
        },
    )
    funds = get_margin_data(_token())
    assert funds["availablecash"] == "50000.00"
    assert funds["m2munrealized"] == "1500.00"
    assert funds["utiliseddebits"] == "50000.00"


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
