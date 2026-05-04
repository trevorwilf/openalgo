"""Regression test for the v1 funds intraday-P&L bug.

``services.v1_compat_bridge._funds`` reads
``balance.metadata['last_equity']`` to compute
``m2munrealized = current_equity - last_equity``. Without
``last_equity`` in the adapter's metadata dict, the bridge always
renders ``m2munrealized = 0.00`` on the funds widget for Alpaca
accounts.

Pinned by this test so a future refactor can't drop the field
silently.
"""

from __future__ import annotations

import json

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, PAPER_BASE_URL
from broker.alpaca.api.position_balance_adapters import AlpacaBalanceAdapter


def _token() -> str:
    return json.dumps(
        {
            "api_key": "ak",
            "api_secret": "sk",
            "is_paper": True,
            "base_url": PAPER_BASE_URL,
            "data_base_url": "https://data.alpaca.markets",
        }
    )


def test_balance_metadata_includes_last_equity(monkeypatch):
    """The adapter must surface ``last_equity`` so the v1 bridge can
    compute intraday unrealized P&L (m2munrealized).
    """

    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "id": "acct-uuid-1",
                "account_number": "PA0123456",
                "status": "ACTIVE",
                "currency": "USD",
                "cash": "50000.00",
                "equity": "51500.00",
                "last_equity": "50000.00",
                "buying_power": "100000.00",
                "initial_margin": "0",
                "maintenance_margin": "0",
                "pattern_day_trader": False,
                "trading_blocked": False,
                "transfers_blocked": False,
                "long_market_value": "1500.00",
                "short_market_value": "0",
            },
            request=httpx.Request("GET", f"{PAPER_BASE_URL}/v2/account"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)

    bal = AlpacaBalanceAdapter().get_balance(
        {"broker_code": "alpaca", "auth_token": _token()}
    )
    assert bal.metadata["last_equity"] == "50000.00"
    # Sanity check the other fields still flow through.
    assert bal.metadata["account_id"] == "acct-uuid-1"
    assert bal.metadata["pattern_day_trader"] is False
