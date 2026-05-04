"""Branch M — crypto routing end-to-end (orders + streaming + manifest)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from broker.alpaca.streaming.alpaca_adapter import (
    AlpacaWebSocketAdapter,
    _FEED_URLS,
)
from broker.alpaca.streaming.alpaca_websocket import (
    CRYPTO_FEED_URL,
    DEFAULT_FEED_URL,
)
from domain.enums import (
    OrderSide,
    OrderType,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.errors import UnsupportedCapability
from domain.instrument_ref import InstrumentRef
from domain.orders import NormalizedOrderRequest


PLUGIN = (
    Path(__file__).resolve().parents[3] / "broker" / "alpaca" / "plugin.json"
)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_plugin_declares_crypto_market_family():
    data = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert "CRYPTO" in data["market_families"]
    assert "CRYPTO" in data["supported_venue_codes"]
    assert "SPOT" in data["supported_asset_classes"]


# ---------------------------------------------------------------------------
# Order routing — symbol round-trip + extended_hours suppression
# ---------------------------------------------------------------------------


class _CryptoResolved:
    def __init__(self, canonical_symbol="BTC-USD", broker_native=None):
        self.instrument_id = "00000000-0000-0000-0000-0000000000ff"
        self.venue_code = "CRYPTO"
        self.canonical_symbol = canonical_symbol
        self.broker_native_symbol = broker_native
        self.broker_native_token = "alpaca-crypto-id"
        self.supports_fractional = True
        self.currency = "USD"


def _crypto_order(
    *,
    canonical_symbol="BTC-USD",
    order_type=OrderType.MARKET,
    qty="0.5",
    price=None,
    session=Session.REGULAR,
):
    return NormalizedOrderRequest(
        instrument=InstrumentRef(
            venue_code="CRYPTO", canonical_symbol=canonical_symbol
        ),
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Decimal(qty),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal(price) if price is not None else None,
        time_in_force=TimeInForce.GTC,
        session=session,
    )


def _ctx():
    return type("Ctx", (), {"broker_code": "alpaca", "account_id": "fake"})()


def test_validate_accepts_crypto_venue():
    AlpacaOrderTranslator().validate(
        _crypto_order(), _CryptoResolved(), _ctx()
    )


def test_to_native_translates_dash_to_slash_for_crypto():
    """OpenAlgo canonical 'BTC-USD' → Alpaca wire 'BTC/USD'."""
    body = AlpacaOrderTranslator().to_native(
        _crypto_order(), _CryptoResolved(), _ctx()
    )
    assert body["symbol"] == "BTC/USD"


def test_to_native_preserves_broker_native_symbol_when_supplied():
    """If the resolver already gives Alpaca's slash form, don't double-
    translate.
    """
    inst = _CryptoResolved(broker_native="ETH/USD")
    body = AlpacaOrderTranslator().to_native(
        _crypto_order(canonical_symbol="ETH-USD"), inst, _ctx()
    )
    assert body["symbol"] == "ETH/USD"


def test_to_native_does_not_translate_equity_dash_symbols():
    """Equity tickers that happen to contain '-' (e.g. BRK-B) must NOT
    be translated.
    """
    class _EquityResolvedDash:
        instrument_id = "x"
        venue_code = "XNYS"
        canonical_symbol = "BRK-B"
        broker_native_symbol = "BRK-B"
        broker_native_token = "x"
        supports_fractional = True
        currency = "USD"

    order = NormalizedOrderRequest(
        instrument=InstrumentRef(venue_code="XNYS", canonical_symbol="BRK-B"),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.WHOLE,
        price=Decimal("420.00"),
        time_in_force=TimeInForce.DAY,
    )
    body = AlpacaOrderTranslator().to_native(
        order, _EquityResolvedDash(), _ctx()
    )
    assert body["symbol"] == "BRK-B"


def test_to_native_drops_extended_hours_flag_for_crypto():
    """Crypto trades 24/7; extended_hours is a no-op and gets stripped."""
    body = AlpacaOrderTranslator().to_native(
        _crypto_order(session=Session.PRE_MARKET),
        _CryptoResolved(),
        _ctx(),
    )
    assert "extended_hours" not in body


# ---------------------------------------------------------------------------
# Streaming — feed selection + cross-feed subscription gates
# ---------------------------------------------------------------------------


def _fake_auth():
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _make_adapter(monkeypatch=None, *, feed=None) -> AlpacaWebSocketAdapter:
    if monkeypatch is not None:
        monkeypatch.delenv("ALPACA_STREAM_BASE", raising=False)
        if feed is not None:
            monkeypatch.setenv("ALPACA_STREAM_FEED", feed)
        else:
            monkeypatch.delenv("ALPACA_STREAM_FEED", raising=False)
    adapter = AlpacaWebSocketAdapter()
    adapter._auth = _fake_auth()
    adapter.publish_market_data = MagicMock()  # type: ignore[method-assign]
    adapter._ws = MagicMock()
    return adapter


def test_default_feed_is_iex(monkeypatch):
    adapter = _make_adapter(monkeypatch)
    assert adapter._resolve_feed_url() == DEFAULT_FEED_URL
    assert adapter._feed_kind() == "iex"


def test_alpaca_stream_feed_crypto_picks_crypto_feed(monkeypatch):
    adapter = _make_adapter(monkeypatch, feed="crypto")
    assert adapter._resolve_feed_url() == CRYPTO_FEED_URL
    assert adapter._feed_kind() == "crypto"


def test_alpaca_stream_feed_sip_picks_sip(monkeypatch):
    adapter = _make_adapter(monkeypatch, feed="sip")
    assert adapter._resolve_feed_url() == _FEED_URLS["sip"]
    assert adapter._feed_kind() == "sip"


def test_alpaca_stream_base_with_feed_suffix_returns_verbatim(monkeypatch):
    """When ``ALPACA_STREAM_BASE`` already names a feed (ends in
    ``/iex`` / ``/sip`` / ``/v1beta3/crypto/...``), the resolver
    treats it as a complete URL and returns it verbatim. This is the
    legacy "full-URL override" contract operators relied on.
    """
    monkeypatch.setenv("ALPACA_STREAM_BASE", "wss://custom.alpaca/test/iex")
    monkeypatch.setenv("ALPACA_STREAM_FEED", "crypto")
    adapter = AlpacaWebSocketAdapter()
    adapter._auth = _fake_auth()
    assert adapter._resolve_feed_url() == "wss://custom.alpaca/test/iex"


def test_alpaca_stream_base_without_feed_suffix_appends_feed(monkeypatch):
    """When ``ALPACA_STREAM_BASE`` is a *base* URL (doesn't already
    name a feed), the resolver appends the feed selector. This is
    the v6-polish-1 fix that resolved the user-reported 404 on
    handshake when ``ALPACA_STREAM_BASE='wss://stream.data.alpaca.markets/v2'``
    was set without ``/iex``.
    """
    monkeypatch.setenv("ALPACA_STREAM_BASE", "wss://custom.alpaca/test")
    monkeypatch.setenv("ALPACA_STREAM_FEED", "crypto")
    adapter = AlpacaWebSocketAdapter()
    adapter._auth = _fake_auth()
    assert adapter._resolve_feed_url() == "wss://custom.alpaca/test/crypto"


def test_subscribe_to_crypto_on_iex_feed_returns_feed_mismatch(monkeypatch):
    adapter = _make_adapter(monkeypatch)  # iex by default
    resp = adapter.subscribe("BTC-USD", "CRYPTO", mode=2)
    assert resp["status"] == "error"
    assert resp["code"] == "feed_mismatch"


def test_subscribe_to_equity_on_crypto_feed_returns_feed_mismatch(monkeypatch):
    adapter = _make_adapter(monkeypatch, feed="crypto")
    resp = adapter.subscribe("AAPL", "XNAS", mode=2)
    assert resp["status"] == "error"
    assert resp["code"] == "feed_mismatch"


def test_subscribe_crypto_translates_dash_to_slash(monkeypatch):
    adapter = _make_adapter(monkeypatch, feed="crypto")
    resp = adapter.subscribe("BTC-USD", "CRYPTO", mode=2)
    assert resp["status"] == "success"
    assert resp["broker_symbol"] == "BTC/USD"
    # WS got the slash-form symbol on the wire.
    adapter._ws.subscribe.assert_called_once_with(
        trades=["BTC/USD"], quotes=["BTC/USD"]
    )


def test_subscribe_equity_does_not_translate_symbol(monkeypatch):
    adapter = _make_adapter(monkeypatch)  # iex
    resp = adapter.subscribe("AAPL", "XNAS", mode=2)
    assert resp["status"] == "success"
    assert resp["broker_symbol"] == "AAPL"
    adapter._ws.subscribe.assert_called_once_with(
        trades=["AAPL"], quotes=["AAPL"]
    )
