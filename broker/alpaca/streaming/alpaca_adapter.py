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
    DEFAULT_FEED_URL,
    AlpacaWebSocketClient,
)
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
        feed_url = os.environ.get("ALPACA_STREAM_BASE", DEFAULT_FEED_URL)
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

        # Track the broader of LTP / Quote per symbol so consumer
        # downgrades don't lose the bid/ask publish.
        prior = self._modes.get(symbol, 0)
        self._modes[symbol] = max(prior, mode)

        if prior == 0:
            # First subscription for this symbol — open both trade
            # and quote channels at the broker. The mode gate at
            # publish time decides which payloads we forward.
            self._ws.subscribe(trades=[symbol], quotes=[symbol])
        return {
            "status": "ok",
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "broker_subscribed": ["trades", "quotes"],
        }

    def unsubscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = _QUOTE_MODE,
    ) -> dict[str, Any]:
        if self._ws is None:
            return {"status": "error", "code": "not_connected"}
        if symbol not in self._modes:
            return {"status": "ok", "symbol": symbol, "noop": True}
        self._modes.pop(symbol, None)
        self._ws.unsubscribe(trades=[symbol], quotes=[symbol])
        return {"status": "ok", "symbol": symbol, "exchange": exchange}

    # ---- frame handlers (called on the WS reader thread) ----------------

    def _on_trade(self, frame: dict[str, Any]) -> None:
        symbol = frame.get("S")
        price = frame.get("p")
        size = frame.get("s")
        ts = frame.get("t")
        if not symbol or price is None:
            return
        # Trade frames feed LTP for both LTP-mode and Quote-mode subs.
        topic = f"{self.broker_name.upper()}:{symbol}:LTP"
        payload = {
            "broker": self.broker_name,
            "symbol": symbol,
            "exchange": _venue_for(frame),
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
        topic = f"{self.broker_name.upper()}:{symbol}:QUOTE"
        payload = {
            "broker": self.broker_name,
            "symbol": symbol,
            "exchange": _venue_for(frame),
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
# "Q" = NASDAQ, "N" = NYSE, etc.). When absent (compact frames or
# crypto), fall back to a generic US placeholder so downstream
# consumers always see SOMETHING. The canonical OpenAlgo venue
# resolution lives in ``database.instruments_repo``; this is a
# best-effort hint for clients that filter by exchange code.
_TAPE_TO_VENUE: dict[str, str] = {
    "V": "IEXG",
    "Q": "XNAS",
    "N": "XNYS",
    "P": "ARCX",
    "Z": "BATS",
}


def _venue_for(frame: dict[str, Any]) -> str:
    tape = frame.get("x") or frame.get("ax") or frame.get("bx")
    if tape and tape in _TAPE_TO_VENUE:
        return _TAPE_TO_VENUE[tape]
    return "XNAS"


__all__ = ["AlpacaWebSocketAdapter"]
