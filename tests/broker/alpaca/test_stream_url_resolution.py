"""Contract test for ``AlpacaWebSocketAdapter._resolve_feed_url``.

The user-reported 404 on WebSocket handshake was caused by an
``ALPACA_STREAM_BASE`` env var set to ``wss://stream.data.alpaca.markets/v2``
(without a feed suffix). The legacy resolver returned that string
verbatim, which 404s because Alpaca's stream is keyed on
``/v2/iex`` / ``/v2/sip`` / ``/v1beta3/crypto/us``. The new resolver
treats a bare ``/v2`` (or trailing slash) as a base and appends the
feed selector — preserving full-URL overrides while fixing the
common base-URL mistake.
"""

from __future__ import annotations

import pytest

from broker.alpaca.streaming.alpaca_adapter import (
    AlpacaWebSocketAdapter,
    CRYPTO_FEED_URL,
)


_DEFAULT_IEX = "wss://stream.data.alpaca.markets/v2/iex"
_DEFAULT_SIP = "wss://stream.data.alpaca.markets/v2/sip"


@pytest.mark.parametrize(
    "base, feed, expected",
    [
        # ---- Bare /v2 base — append the feed selector. -------------------
        ("wss://stream.data.alpaca.markets/v2", "iex", _DEFAULT_IEX),
        ("wss://stream.data.alpaca.markets/v2", "sip", _DEFAULT_SIP),
        ("wss://stream.data.alpaca.markets/v2/", "iex", _DEFAULT_IEX),
        # ---- Already-complete IEX/SIP URL — return as-is. ----------------
        (_DEFAULT_IEX, "iex", _DEFAULT_IEX),
        (_DEFAULT_SIP, "sip", _DEFAULT_SIP),
        (_DEFAULT_IEX + "/", "iex", _DEFAULT_IEX),  # trailing slash tolerated
        # ---- Crypto base: full URL is honored verbatim. ------------------
        (CRYPTO_FEED_URL, "crypto", CRYPTO_FEED_URL),
        # ---- Bare /v2 + crypto feed: redirect to canonical crypto URL.
        # The operator picked the wrong version path; we honor the
        # feed selector and the canonical asset-class URL.
        ("wss://stream.data.alpaca.markets/v2", "crypto", CRYPTO_FEED_URL),
    ],
)
def test_compose_feed_url(base, feed, expected):
    assert AlpacaWebSocketAdapter._compose_feed_url(base, feed) == expected


def test_resolve_feed_url_uses_canonical_default(monkeypatch):
    monkeypatch.delenv("ALPACA_STREAM_BASE", raising=False)
    monkeypatch.delenv("ALPACA_STREAM_FEED", raising=False)
    adapter = AlpacaWebSocketAdapter.__new__(AlpacaWebSocketAdapter)
    assert adapter._resolve_feed_url() == _DEFAULT_IEX


def test_resolve_feed_url_honors_explicit_full_url(monkeypatch):
    monkeypatch.setenv("ALPACA_STREAM_BASE", _DEFAULT_SIP)
    monkeypatch.delenv("ALPACA_STREAM_FEED", raising=False)
    adapter = AlpacaWebSocketAdapter.__new__(AlpacaWebSocketAdapter)
    assert adapter._resolve_feed_url() == _DEFAULT_SIP


def test_resolve_feed_url_appends_feed_to_bare_base(monkeypatch):
    """Reproduces the original user-reported 404 scenario: bare /v2
    base now gets ``/iex`` appended instead of being returned as-is.
    """
    monkeypatch.setenv(
        "ALPACA_STREAM_BASE", "wss://stream.data.alpaca.markets/v2"
    )
    monkeypatch.delenv("ALPACA_STREAM_FEED", raising=False)
    adapter = AlpacaWebSocketAdapter.__new__(AlpacaWebSocketAdapter)
    assert adapter._resolve_feed_url() == _DEFAULT_IEX
