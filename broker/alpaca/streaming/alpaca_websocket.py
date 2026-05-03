"""Alpaca WebSocket protocol — auth + subscribe + frame dispatch.

This module is a thin protocol wrapper around Alpaca's market-data
WebSocket. It does NOT bind ZeroMQ or talk to OpenAlgo's normalized
tick schema — the :class:`AlpacaWebSocketAdapter` is the integration
layer that does that.

Endpoints (per Alpaca's docs):

  Equities, free IEX feed:
    wss://stream.data.alpaca.markets/v2/iex
  Equities, paid SIP feed:
    wss://stream.data.alpaca.markets/v2/sip
  Crypto:
    wss://stream.data.alpaca.markets/v1beta3/crypto/us

Wire protocol (JSON frames over text WebSocket):

  Auth:        client → ``{"action":"auth","key":"...","secret":"..."}``
               server → ``[{"T":"success","msg":"authenticated"}]``
  Subscribe:   client → ``{"action":"subscribe","trades":["AAPL"],"quotes":["AAPL"]}``
               server → ``[{"T":"subscription","trades":["AAPL"],...}]``
  Trade tick:  ``[{"T":"t","S":"AAPL","p":189.5,"s":100,"x":"V","t":"...","i":12345}]``
  Quote tick:  ``[{"T":"q","S":"AAPL","bp":189.4,"bs":2,"ap":189.6,"as":3,"t":"..."}]``

Frames are batched — every server message is a JSON array of one or
more events.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import websocket  # websocket-client

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from utils.logging import get_logger

logger = get_logger(__name__)


# Default to the free IEX feed; SIP requires a paid Alpaca subscription.
DEFAULT_FEED_URL = "wss://stream.data.alpaca.markets/v2/iex"


class AlpacaWebSocketClient:
    """Single-connection Alpaca WebSocket client.

    Threading model: the underlying ``websocket.WebSocketApp`` runs
    its own loop in a daemon thread. Callers register one handler per
    frame type via the ``on_*`` callbacks. Frame dispatch happens on
    the WS reader thread — handlers must not block.

    Connection lifecycle:

      ``__init__()``  — store config; no network.
      ``start()``     — open socket; auth handshake; spawn reader thread.
      ``subscribe(...)`` / ``unsubscribe(...)`` — runtime sub mutation.
      ``stop()``      — graceful close.
    """

    def __init__(
        self,
        auth: AlpacaAuth | None = None,
        feed_url: str = DEFAULT_FEED_URL,
        on_trade: Callable[[dict[str, Any]], None] | None = None,
        on_quote: Callable[[dict[str, Any]], None] | None = None,
        on_bar: Callable[[dict[str, Any]], None] | None = None,
        on_status: Callable[[str, dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._auth = auth
        self._feed_url = feed_url
        self._on_trade = on_trade
        self._on_quote = on_quote
        self._on_bar = on_bar
        self._on_status = on_status
        self._on_error = on_error

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._authenticated = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.Lock()

        # Active subscription sets — used to resubscribe after reconnect
        # (reconnect is a future enhancement; the sets are tracked now
        # so the API surface is stable).
        self._sub_trades: set[str] = set()
        self._sub_quotes: set[str] = set()
        self._sub_bars: set[str] = set()

    # -- public lifecycle ---------------------------------------------------

    def start(self, timeout: float = 5.0) -> None:
        """Open the socket and complete the auth handshake.

        Blocks until the server confirms ``authenticated`` or the
        timeout elapses, whichever comes first. Raises ``TimeoutError``
        if auth doesn't complete within ``timeout`` seconds.
        """
        auth = self._resolve_auth()
        self._authenticated.clear()
        self._closed.clear()

        self._ws = websocket.WebSocketApp(
            self._feed_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_ws_error,
            on_close=self._on_close,
            header={
                "APCA-API-KEY-ID": auth.headers["APCA-API-KEY-ID"],
                "APCA-API-SECRET-KEY": auth.headers["APCA-API-SECRET-KEY"],
            },
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            name="alpaca-ws-reader",
            daemon=True,
        )
        self._thread.start()

        if not self._authenticated.wait(timeout=timeout):
            raise TimeoutError(
                f"Alpaca WS auth did not complete within {timeout}s"
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Close the socket and wait for the reader thread to exit."""
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Alpaca WS close failed")
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._closed.set()

    # -- subscriptions ------------------------------------------------------

    def subscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
        bars: list[str] | None = None,
    ) -> None:
        """Subscribe to one or more channels.

        Idempotent — repeating an existing subscription is a no-op
        client-side (the broker may still echo a subscription frame).
        """
        with self._lock:
            new_t = [s for s in (trades or []) if s not in self._sub_trades]
            new_q = [s for s in (quotes or []) if s not in self._sub_quotes]
            new_b = [s for s in (bars or []) if s not in self._sub_bars]
            if not (new_t or new_q or new_b):
                return
            self._sub_trades.update(new_t)
            self._sub_quotes.update(new_q)
            self._sub_bars.update(new_b)
            payload: dict[str, Any] = {"action": "subscribe"}
            if new_t:
                payload["trades"] = new_t
            if new_q:
                payload["quotes"] = new_q
            if new_b:
                payload["bars"] = new_b
        self._send(payload)

    def unsubscribe(
        self,
        trades: list[str] | None = None,
        quotes: list[str] | None = None,
        bars: list[str] | None = None,
    ) -> None:
        with self._lock:
            drop_t = [s for s in (trades or []) if s in self._sub_trades]
            drop_q = [s for s in (quotes or []) if s in self._sub_quotes]
            drop_b = [s for s in (bars or []) if s in self._sub_bars]
            if not (drop_t or drop_q or drop_b):
                return
            self._sub_trades.difference_update(drop_t)
            self._sub_quotes.difference_update(drop_q)
            self._sub_bars.difference_update(drop_b)
            payload: dict[str, Any] = {"action": "unsubscribe"}
            if drop_t:
                payload["trades"] = drop_t
            if drop_q:
                payload["quotes"] = drop_q
            if drop_b:
                payload["bars"] = drop_b
        self._send(payload)

    # -- internal: socket plumbing -----------------------------------------

    def _resolve_auth(self) -> AlpacaAuth:
        return self._auth if self._auth is not None else authenticate()

    def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Alpaca WS not started — call start() first")
        self._ws.send(json.dumps(payload))

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        # Alpaca's wire format requires the auth message even though
        # we set the headers above (the header form is accepted on
        # some endpoints but not all; the in-band form is canonical).
        auth = self._resolve_auth()
        ws.send(
            json.dumps(
                {
                    "action": "auth",
                    "key": auth.headers["APCA-API-KEY-ID"],
                    "secret": auth.headers["APCA-API-SECRET-KEY"],
                }
            )
        )

    def _on_message(
        self, ws: websocket.WebSocketApp, message: str | bytes
    ) -> None:
        try:
            text = message.decode("utf-8") if isinstance(message, (bytes, bytearray)) else message
            frames = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Alpaca WS frame decode error: %s", exc)
            return
        if not isinstance(frames, list):
            frames = [frames]
        for frame in frames:
            self._dispatch(frame)

    def _dispatch(self, frame: dict[str, Any]) -> None:
        kind = frame.get("T")
        if kind == "success":
            msg = frame.get("msg")
            if msg == "authenticated":
                self._authenticated.set()
            if self._on_status is not None:
                try:
                    self._on_status("success", frame)
                except Exception:  # pragma: no cover - handler bug
                    logger.exception("alpaca on_status handler raised")
            return
        if kind == "error":
            logger.error(
                "Alpaca WS error frame: code=%s msg=%r",
                frame.get("code"),
                frame.get("msg"),
            )
            if self._on_status is not None:
                try:
                    self._on_status("error", frame)
                except Exception:  # pragma: no cover
                    logger.exception("alpaca on_status handler raised")
            return
        if kind == "subscription":
            if self._on_status is not None:
                try:
                    self._on_status("subscription", frame)
                except Exception:  # pragma: no cover
                    logger.exception("alpaca on_status handler raised")
            return
        if kind == "t" and self._on_trade is not None:
            try:
                self._on_trade(frame)
            except Exception:  # pragma: no cover
                logger.exception("alpaca on_trade handler raised")
            return
        if kind == "q" and self._on_quote is not None:
            try:
                self._on_quote(frame)
            except Exception:  # pragma: no cover
                logger.exception("alpaca on_quote handler raised")
            return
        if kind == "b" and self._on_bar is not None:
            try:
                self._on_bar(frame)
            except Exception:  # pragma: no cover
                logger.exception("alpaca on_bar handler raised")
            return
        # Unknown frame type — log at debug so the firehose stays quiet.
        logger.debug("Alpaca WS unhandled frame type: %s", kind)

    def _on_ws_error(
        self, ws: websocket.WebSocketApp, exc: Exception
    ) -> None:
        logger.error("Alpaca WS error: %s", exc)
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:  # pragma: no cover
                logger.exception("alpaca on_error handler raised")

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        status_code: int | None,
        reason: str | None,
    ) -> None:
        logger.info(
            "Alpaca WS closed: code=%s reason=%s", status_code, reason
        )
        self._closed.set()


__all__ = [
    "AlpacaWebSocketClient",
    "DEFAULT_FEED_URL",
]
