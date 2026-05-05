"""Regression: ``AlpacaPositionAdapter`` returns crypto positions
with the OpenAlgo canonical (dash) form, not Alpaca's wire (slash)
form.

Bug: ``canonical_symbol = symbol`` directly stored Alpaca's
``BTC/USD`` for crypto positions, while ``instrument_sync`` stores
``BTC-USD`` as the canonical row in the instruments table. A v2
caller looking up the position's canonical_symbol against
``/api/v2/instruments/search`` got a 404.

Fix: convert ``/`` → ``-`` for crypto rows, matching the
instrument_sync convention. The original ``BTC/USD`` is preserved
in ``metadata["broker_symbol"]`` for round-trips back to
``/v2/orders``.
"""

from __future__ import annotations

import json

import httpx

from broker.alpaca.api.auth_api import PAPER_BASE_URL, DATA_BASE_URL
from broker.alpaca.api.position_balance_adapters import AlpacaPositionAdapter


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


def _patch_positions(monkeypatch, body):
    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json=body,
            request=httpx.Request("GET", f"{PAPER_BASE_URL}{url}"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)


def test_crypto_position_canonical_uses_dash(monkeypatch):
    _patch_positions(monkeypatch, [
        {
            "asset_id": "btc-uuid",
            "symbol": "BTC/USD",
            "qty": "0.5",
            "side": "long",
            "asset_class": "crypto",
            "exchange": "CRYPTO",
            "avg_entry_price": "60000",
            "current_price": "62000",
        },
    ])
    positions = AlpacaPositionAdapter().get_positions(
        {"broker_code": "alpaca", "auth_token": _token()}
    )
    assert len(positions) == 1
    btc = positions[0]
    assert btc.canonical_symbol == "BTC-USD"
    assert btc.venue_code == "ALPACA_CRYPTO"
    # Raw Alpaca form preserved in metadata for round-trips.
    assert btc.metadata["broker_symbol"] == "BTC/USD"


def test_equity_position_unchanged(monkeypatch):
    """US equity round-trip is identity — no replacement."""
    _patch_positions(monkeypatch, [
        {
            "asset_id": "aapl-uuid",
            "symbol": "AAPL",
            "qty": "10",
            "side": "long",
            "asset_class": "us_equity",
            "exchange": "NASDAQ",
            "avg_entry_price": "175.00",
        },
    ])
    positions = AlpacaPositionAdapter().get_positions(
        {"broker_code": "alpaca", "auth_token": _token()}
    )
    aapl = positions[0]
    assert aapl.canonical_symbol == "AAPL"
    assert aapl.venue_code == "XNAS"
    assert aapl.metadata["broker_symbol"] == "AAPL"
