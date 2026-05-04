"""Alpaca WebSocket adapter — bridges :class:`AlpacaWebSocketClient`
into OpenAlgo's :class:`BaseBrokerWebSocketAdapter` ZeroMQ surface.

MVP scope (Branch D):
  * Single connection to the IEX equities feed
    (``wss://stream.data.alpaca.markets/v2/iex``).
  * Trade and quote frames; bars are wired but currently unused
    (OpenAlgo's tick model is point-in-time, not OHLCV).
  * Mode 1 (LTP) and mode 2 (Quote) supported. Depth (mode 4) is
    declared unsupported because Alpaca's v2 data API exposes
    top-of-book only.
  * No reconnect-with-backoff loop yet — a dropped connection
    surfaces via the ``on_error`` callback. Reconnect lives in a
    follow-up branch.
  * No pooling / fan-out across multiple connections — Alpaca's free
    tier allows a single connection per account.
"""

from __future__ import annotations

import os
from typing import Any

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from broker.alpaca.streaming.alpaca_websocket import (
    CRYPTO_FEED_URL,
    DEFAULT_FEED_URL,
    AlpacaWebSocketClient,
)


# Branch M — feed selection. ``ALPACA_STREAM_FEED`` overrides the
# default IEX feed:
#
#   iex     — wss://stream.data.alpaca.markets/v2/iex     (free, default)
#   sip     — wss://stream.data.alpaca.markets/v2/sip     (paid SIP)
#   crypto  — wss://stream.data.alpaca.markets/v1beta3/crypto/us
#
# A single adapter instance subscribes to a single feed; mixing
# equity and crypto subscriptions in one adapter is not supported
# (Alpaca's wire protocol uses one URL per asset family). Spawn a
# second adapter for the other family.
_FEED_URLS: dict[str, str] = {
    "iex": "wss://stream.data.alpaca.markets/v2/iex",
    "sip": "wss://stream.data.alpaca.markets/v2/sip",
    "crypto": CRYPTO_FEED_URL,
}
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter


_LTP_MODE = 1
_QUOTE_MODE = 2
_DEPTH_MODE = 4


class AlpacaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Alpaca-specific WebSocket adapter.

    Subscriptions are tracked per ``(symbol, mode)`` pair. The
    underlying Alpaca client always subscribes to BOTH the trade and
    quote channels for a symbol because LTP is derived from trade
    frames and bid/ask comes from quote frames; mode is enforced
    client-side by gating which topic gets published.
    """

    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger("alpaca_websocket")
        self.broker_name = "alpaca"
        self.user_id: str | None = None
        self._auth: AlpacaAuth | None = None
        self._ws: AlpacaWebSocketClient | None = None
        # Per-symbol mode tracker. Subscribing twice with different
        # modes keeps the broader of the two so a downgrade
        # (Quote -> LTP) does not silently drop the bid/ask publish.
        self._modes: dict[str, int] = {}
        # Track the exchange the client subscribed under so the
        # publish topic uses ``{subscribed_venue}_{symbol}_{mode}``
        # rather than the tape-derived venue. Alpaca's IEX feed
        # tags quotes with tape "V" → IEXG, but clients subscribe
        # under XNAS / XNYS / etc.; the subscription index keys on
        # (symbol, exchange, mode) so a mismatch silently drops
        # ticks. Fix: record the subscribed venue and reuse it on
        # publish.
        self._subscribed_venue: dict[str, str] = {}

    # ---- BaseBrokerWebSocketAdapter abstract methods ---------------------

    def initialize(
        self,
        broker_name: str,
        user_id: str,
        auth_data: dict[str, str] | None = None,
    ) -> None:
        self.broker_name = broker_name
        self.user_id = user_id
        if auth_data and "api_key" in auth_data and "api_secret" in auth_data:
            self._auth = AlpacaAuth(
                base_url=auth_data.get(
                    "base_url", "https://paper-api.alpaca.markets"
                ),
                data_base_url=auth_data.get(
                    "data_base_url", "https://data.alpaca.markets"
                ),
                headers={
                    "APCA-API-KEY-ID": auth_data["api_key"],
                    "APCA-API-SECRET-KEY": auth_data["api_secret"],
                },
            )
        else:
            # Fall back to env-var resolution (Branch A's dual-source).
            self._auth = authenticate()
        self.logger.info(
            "alpaca adapter initialized for user=%s mode=%s",
            user_id,
            "paper" if self._auth.is_paper else "live",
        )

    def connect(self) -> None:
        if self._auth is None:
            raise RuntimeError(
                "AlpacaWebSocketAdapter.connect() before initialize()"
            )
        feed_url = self._resolve_feed_url()
        self._ws = AlpacaWebSocketClient(
            auth=self._auth,
            feed_url=feed_url,
            on_trade=self._on_trade,
            on_quote=self._on_quote,
            on_status=self._on_status,
            on_error=self._on_error,
        )
        self._ws.start()
        self.connected = True
        self.logger.info("alpaca adapter connected to %s", feed_url)

    def disconnect(self) -> None:
        try:
            if self._ws is not None:
                self._ws.stop()
        finally:
            self._ws = None
            self.connected = False
            self.cleanup_zmq()

    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = _QUOTE_MODE,
        depth_level: int = 5,
    ) -> dict[str, Any]:
        if mode == _DEPTH_MODE:
            return {
                "status": "error",
                "code": "unsupported_capability",
                "message": (
                    "Alpaca v2 data API exposes top-of-book only; mode 4 "
                    "(depth) is not supported."
                ),
            }
        if self._ws is None:
            return {"status": "error", "code": "not_connected"}

        # Branch M — refuse to subscribe to a symbol on the wrong
        # feed. CRYPTO venues only flow over the crypto feed; equity
        # venues only over IEX / SIP. Mixed-asset adapters are not
        # supported (Alpaca uses one URL per asset family).
        feed_kind = self._feed_kind()
        is_crypto_venue = exchange.upper() == "CRYPTO"
        if is_crypto_venue and feed_kind != "crypto":
            return {
                "status": "error",
                "code": "feed_mismatch",
                "message": (
                    f"Cannot subscribe to CRYPTO venue {symbol!r} on the "
                    f"{feed_kind!r} feed; set ALPACA_STREAM_FEED=crypto "
                    "and reconnect, or use a separate adapter instance."
                ),
            }
        if not is_crypto_venue and feed_kind == "crypto":
            return {
                "status": "error",
                "code": "feed_mismatch",
                "message": (
                    f"Cannot subscribe to equity venue {exchange!r} on the "
                    "crypto feed; set ALPACA_STREAM_FEED=iex (or sip) and "
                    "reconnect."
                ),
            }

        # Branch M — translate OpenAlgo's BTC-USD into Alpaca's
        # BTC/USD wire form for crypto subscriptions.
        broker_symbol = (
            symbol.replace("-", "/") if is_crypto_venue and "-" in symbol else symbol
        )
        # Track the broader of LTP / Quote per the BROKER's symbol
        # form so the inbound frame's S field matches.
        prior = self._modes.get(broker_symbol, 0)
        self._modes[broker_symbol] = max(prior, mode)
        # Remember the subscribed venue for publish-topic routing.
        self._subscribed_venue[broker_symbol] = exchange

        if prior == 0:
            # First subscription for this symbol — open both trade
            # and quote channels at the broker. The mode gate at
            # publish time decides which payloads we forward.
            self._ws.subscribe(
                trades=[broker_symbol], quotes=[broker_symbol]
            )
        return {
            "status": "success",
            "symbol": symbol,
            "broker_symbol": broker_symbol,
            "exchange": exchange,
            "mode": mode,
            "feed": feed_kind,
            "broker_subscribed": ["trades", "quotes"],
        }

    # ---- feed selection helpers (Branch M) ------------------------------

    def _resolve_feed_url(self) -> str:
        """Pick the WS URL.

        Resolution order:

        1. ``ALPACA_STREAM_BASE`` env var, when set:

           * If it already ends in a recognized feed suffix
             (``/iex``, ``/sip``, ``/v1beta3/crypto/us``, …), it is
             treated as a *complete* URL and returned verbatim.
           * Otherwise it is treated as a *base* URL and the feed
             suffix derived from ``ALPACA_STREAM_FEED`` (default
             ``iex``) is appended. This is what most operators
             actually want and avoids the 404-on-handshake trap when
             the env var is ``wss://stream.data.alpaca.markets/v2``
             (no feed suffix).

        2. Otherwise, the canonical map keyed on
           ``ALPACA_STREAM_FEED`` (default ``iex``).
        """
        explicit = os.environ.get("ALPACA_STREAM_BASE", "").strip()
        feed = os.environ.get("ALPACA_STREAM_FEED", "iex").strip().lower()
        if explicit:
            return self._compose_feed_url(explicit, feed)
        return _FEED_URLS.get(feed, DEFAULT_FEED_URL)

    @staticmethod
    def _compose_feed_url(base: str, feed: str) -> str:
        """Combine ``ALPACA_STREAM_BASE`` with the feed selector.

        If ``base`` already names a feed (ends with ``/iex``, ``/sip``,
        or contains ``/v1beta3/crypto/``), it's returned verbatim. If
        the base is a bare ``…/v2`` or trailing-slash URL, we append
        ``feed``.
        """
        clean = base.rstrip("/")
        if clean.endswith(("/iex", "/sip")) or "/v1beta3/crypto/" in clean:
            return clean
        # Bare ``/v2`` (or similar) — append the feed selector.
        if clean.endswith("/v2"):
            if feed == "crypto":
                # Crypto lives on a different version path; if the
                # operator pinned ``/v2`` AND asked for crypto we
                # ignore the base and use the crypto canonical URL.
                return CRYPTO_FEED_URL
            return f"{clean}/{feed}"
        # Any other shape — append /v2/<feed> as a best-effort
        # default. Equivalent to the legacy "treat as override"
        # behavior for unusual values.
        return f"{clean}/{feed}" if not clean.endswith(f"/{feed}") else clean

    def _feed_kind(self) -> str:
        """Return ``iex`` / ``sip`` / ``crypto`` for the current connection.

        Used by subscribe() to gate cross-feed subscriptions.
        """
        url = self._resolve_feed_url()
        if "/crypto/" in url:
            return "crypto"
        if url.endswith("/sip"):
            return "sip"
        return "iex"

    def unsubscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = _QUOTE_MODE,
    ) -> dict[str, Any]:
        if self._ws is None:
            return {"status": "error", "code": "not_connected"}
        if symbol not in self._modes:
            return {"status": "success", "symbol": symbol, "noop": True}
        self._modes.pop(symbol, None)
        self._ws.unsubscribe(trades=[symbol], quotes=[symbol])
        return {"status": "success", "symbol": symbol, "exchange": exchange}

    # ---- frame handlers (called on the WS reader thread) ----------------

    def _on_trade(self, frame: dict[str, Any]) -> None:
        symbol = frame.get("S")
        price = frame.get("p")
        size = frame.get("s")
        ts = frame.get("t")
        if not symbol or price is None:
            return
        # Trade frames feed LTP for both LTP-mode and Quote-mode subs.
        # Topic format matches the WebSocket proxy server's expected
        # ``{exchange}_{symbol}_{mode}`` shape (split by ``_``). Use
        # the SUBSCRIBED venue (XNAS / XNYS / ARCX / BATS) rather
        # than the tape-derived venue (IEXG / etc.) — the server's
        # subscription index keys on the subscribed venue, so any
        # tape-based topic silently misses the lookup.
        subscribed_venue = self._subscribed_venue.get(symbol) or _venue_for(frame)
        tape_venue = _venue_for(frame)
        topic = f"{subscribed_venue}_{symbol}_LTP"
        payload = {
            "broker": self.broker_name,
            "symbol": symbol,
            "exchange": subscribed_venue,
            "tape_venue": tape_venue,  # metadata: where the print actually happened
            "ltp": price,
            "last_traded_quantity": size,
            "timestamp": ts,
            "kind": "trade",
        }
        self.publish_market_data(topic, payload)

    def _on_quote(self, frame: dict[str, Any]) -> None:
        symbol = frame.get("S")
        if not symbol:
            return
        if self._modes.get(symbol, 0) < _QUOTE_MODE:
            # LTP-only subscriber; drop the bid/ask frame.
            return
        subscribed_venue = self._subscribed_venue.get(symbol) or _venue_for(frame)
        tape_venue = _venue_for(frame)
        topic = f"{subscribed_venue}_{symbol}_QUOTE"
        payload = {
            "broker": self.broker_name,
            "symbol": symbol,
            "exchange": subscribed_venue,
            "tape_venue": tape_venue,
            "bid": frame.get("bp"),
            "bid_size": frame.get("bs"),
            "ask": frame.get("ap"),
            "ask_size": frame.get("as"),
            "timestamp": frame.get("t"),
            "kind": "quote",
        }
        self.publish_market_data(topic, payload)

    def _on_status(self, kind: str, frame: dict[str, Any]) -> None:
        if kind == "error":
            self.logger.error(
                "alpaca status error: code=%s msg=%r",
                frame.get("code"),
                frame.get("msg"),
            )
        else:
            self.logger.debug("alpaca status %s: %s", kind, frame)

    def _on_error(self, exc: Exception) -> None:
        self.logger.error("alpaca ws error: %s", exc)


# Alpaca's frame uses an ``x`` field for the venue tape ("V" = IEX,
# Branch N — single source of truth for tape → venue lives in
# ``broker.alpaca.mapping.transform_data.ALPACA_TAPE_TO_VENUE``;
# the adapter delegates to ``venue_from_alpaca_tape`` which falls
# back to XNAS for unknown / missing tapes (best-effort hint for
# clients that filter by exchange code; canonical resolution lives
# in ``database.instruments_repo``).


def _venue_for(frame: dict[str, Any]) -> str:
    from broker.alpaca.mapping.transform_data import venue_from_alpaca_tape

    tape = frame.get("x") or frame.get("ax") or frame.get("bx")
    return venue_from_alpaca_tape(tape)


__all__ = ["AlpacaWebSocketAdapter"]
