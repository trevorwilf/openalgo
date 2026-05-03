"""Alpaca trade-updates stream.

Connects to Alpaca's broker WebSocket (separate from the market-data
feed) and listens for ``trade_updates`` events. Each update is
translated into one of OpenAlgo's order-event types and published to
:mod:`utils.event_bus`, where the existing SocketIO subscriber will
push it to the React UI.

URLs (per Alpaca docs):

  Paper:  wss://paper-api.alpaca.markets/stream
  Live:   wss://api.alpaca.markets/stream

Auth is in-band:
  → ``{"action":"authenticate","data":{"key_id":"…","secret_key":"…"}}``
  ← ``{"stream":"authorization","data":{"status":"authorized","action":"authenticate"}}``

Subscribe:
  → ``{"action":"listen","data":{"streams":["trade_updates"]}}``
  ← ``{"stream":"listening","data":{"streams":["trade_updates"]}}``

Stream frame:
  ``{"stream":"trade_updates","data":{"event":"<E>","order":{…},"price":"<P>",
     "qty":"<Q>","timestamp":"…"}}``

The ``event`` field is the canonical signal — ``new``, ``fill``,
``partial_fill``, ``canceled``, ``expired``, ``rejected``,
``replaced``, ``pending_cancel``, ``pending_replace``,
``done_for_day``, ``stopped``, ``suspended``. We map each to the
matching OpenAlgo event type and publish it on the bus.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

import websocket

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from utils.logging import get_logger


logger = get_logger(__name__)


_PAPER_URL = "wss://paper-api.alpaca.markets/stream"
_LIVE_URL = "wss://api.alpaca.markets/stream"


def _stream_url_for(auth: AlpacaAuth) -> str:
    return _PAPER_URL if auth.is_paper else _LIVE_URL


class AlpacaTradeUpdatesClient:
    """Long-lived WebSocket client for Alpaca's trade_updates channel.

    Threading: ``websocket.WebSocketApp`` runs ``run_forever`` on a
    daemon thread spawned by :meth:`start`. Frame dispatch happens
    on that thread; handlers must not block.

    Reconnect: the loop reconnects with exponential backoff on
    unexpected close, replaying the trade_updates subscription on
    every successful auth. ``stop()`` is the only graceful exit.
    """

    def __init__(
        self,
        auth: AlpacaAuth | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        *,
        reconnect: bool = True,
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        reconnect_backoff_factor: float = 2.0,
    ) -> None:
        self._auth = auth
        self._on_event = on_event
        self._reconnect = reconnect
        self._reconnect_initial_delay = reconnect_initial_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._reconnect_backoff_factor = reconnect_backoff_factor

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._authenticated = threading.Event()
        self._reconnect_attempt = 0

    def start(self, timeout: float = 5.0) -> None:
        """Open the socket, authenticate, and start the reader loop.

        Blocks until the broker confirms ``authorized`` or the
        timeout elapses.
        """
        self._stop_requested.clear()
        self._authenticated.clear()
        self._reconnect_attempt = 0
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="alpaca-trade-updates-reader",
            daemon=True,
        )
        self._thread.start()
        if not self._authenticated.wait(timeout=timeout):
            self._stop_requested.set()
            try:
                if self._ws is not None:
                    self._ws.close()
            except Exception:  # pragma: no cover
                pass
            raise TimeoutError(
                f"Alpaca trade_updates auth did not complete within {timeout}s"
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Tear the socket down. Idempotent."""
        self._stop_requested.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # pragma: no cover
                logger.exception("Alpaca trade_updates close failed")
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # -- internals -------------------------------------------------------

    def _resolve_auth(self) -> AlpacaAuth:
        return self._auth if self._auth is not None else authenticate()

    def _reader_loop(self) -> None:
        delay = self._reconnect_initial_delay
        first = True
        while not self._stop_requested.is_set():
            if first:
                first = False
            else:
                self._reconnect_attempt += 1
                logger.info(
                    "Alpaca trade_updates reconnect attempt %d in %.1fs",
                    self._reconnect_attempt,
                    delay,
                )
                slept = 0.0
                while slept < delay and not self._stop_requested.is_set():
                    time.sleep(min(0.25, delay - slept))
                    slept += 0.25
                if self._stop_requested.is_set():
                    break
                delay = min(
                    delay * self._reconnect_backoff_factor,
                    self._reconnect_max_delay,
                )

            self._authenticated.clear()
            try:
                auth = self._resolve_auth()
                url = _stream_url_for(auth)
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_close,
                )
                logger.info("Alpaca trade_updates: connecting to %s", url)
                self._ws.run_forever()
            except Exception:  # pragma: no cover
                logger.exception("Alpaca trade_updates reader crashed")

            if not self._reconnect or self._stop_requested.is_set():
                break

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        auth = self._resolve_auth()
        ws.send(
            json.dumps(
                {
                    "action": "authenticate",
                    "data": {
                        "key_id": auth.headers["APCA-API-KEY-ID"],
                        "secret_key": auth.headers["APCA-API-SECRET-KEY"],
                    },
                }
            )
        )

    def _on_message(self, ws: websocket.WebSocketApp, message: str | bytes) -> None:
        try:
            text = message.decode("utf-8") if isinstance(message, (bytes, bytearray)) else message
            frame = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Alpaca trade_updates: malformed frame")
            return

        stream = frame.get("stream")
        data = frame.get("data") or {}

        if stream == "authorization":
            if data.get("status") == "authorized":
                logger.info("Alpaca trade_updates: authorized")
                # subscribe to trade_updates
                ws.send(
                    json.dumps(
                        {
                            "action": "listen",
                            "data": {"streams": ["trade_updates"]},
                        }
                    )
                )
            else:
                logger.error(
                    "Alpaca trade_updates: authorization failed: %s", data
                )
            return

        if stream == "listening":
            self._authenticated.set()
            logger.info(
                "Alpaca trade_updates: listening on %s",
                data.get("streams"),
            )
            return

        if stream == "trade_updates":
            event_type = (data.get("event") or "").lower()
            if not event_type:
                return
            if self._on_event is not None:
                try:
                    self._on_event(event_type, data)
                except Exception:  # pragma: no cover
                    logger.exception("Alpaca trade_updates handler raised")
            return

        # Other broker stream messages (account_updates etc.) are
        # ignored for now.

    def _on_ws_error(self, ws: websocket.WebSocketApp, err: Exception) -> None:
        logger.warning("Alpaca trade_updates WS error: %s", err)

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        close_status_code: int | None,
        close_msg: str | None,
    ) -> None:
        logger.info(
            "Alpaca trade_updates closed: %s / %s",
            close_status_code,
            close_msg,
        )


# ---------------------------------------------------------------------------
# Bus integration — translates Alpaca trade_updates events into the
# canonical OpenAlgo event types and publishes them.
# ---------------------------------------------------------------------------


def publish_trade_update_to_bus(event_type: str, data: dict[str, Any]) -> None:
    """Translate a single trade_updates frame into an OpenAlgo event
    and publish it to ``utils.event_bus``.

    The existing SocketIO subscriber re-emits each event to the React
    UI as ``order_event`` / ``cancel_order_event`` / etc., so the
    user sees fills land in real time.
    """
    from events import (
        OrderCancelledEvent,
        OrderFailedEvent,
        OrderModifiedEvent,
        OrderPlacedEvent,
    )
    from utils.event_bus import bus

    order = data.get("order") or {}
    order_id = order.get("id") or ""
    symbol = (order.get("symbol") or "").upper()
    canonical = AlpacaOrderTranslator.normalize_order_status(
        order.get("status") or event_type
    )

    common = {
        "mode": "live",
        "api_type": "trade_updates",
        "symbol": symbol,
        "exchange": _venue_from_alpaca(order.get("asset_class"), order.get("exchange")),
        "request_data": {"trade_update": event_type, "order_id": order_id},
        "response_data": {"canonical_status": canonical.value, "data": data},
        "api_key": "",
    }

    if event_type in ("new", "accepted"):
        bus.publish(
            OrderPlacedEvent(
                strategy="alpaca-stream",
                action=(order.get("side") or "").upper(),
                quantity=int(float(order.get("qty") or 0)),
                pricetype=(order.get("type") or "").upper(),
                product="MIS",
                orderid=order_id,
                **common,
            )
        )
        return
    if event_type in ("fill", "partial_fill"):
        # Treat fills as OrderModified — a state-change event the UI
        # subscribes to. Fully-filled orders are terminal but the
        # OrderPlaced->fill transition is what the order-book table
        # animates on.
        bus.publish(
            OrderModifiedEvent(orderid=order_id, **common)
        )
        return
    if event_type in ("canceled", "expired", "done_for_day"):
        bus.publish(
            OrderCancelledEvent(
                orderid=order_id,
                status=canonical.value,
                **common,
            )
        )
        return
    if event_type in ("rejected",):
        bus.publish(
            OrderFailedEvent(
                error_message=str(order.get("status") or "rejected"),
                **common,
            )
        )
        return
    if event_type in ("replaced",):
        bus.publish(
            OrderModifiedEvent(orderid=order_id, **common)
        )
        return
    # pending_cancel / pending_replace / suspended / stopped /
    # calculated — all are intermediate signals; surface as
    # OrderModified so the UI can refresh.
    bus.publish(OrderModifiedEvent(orderid=order_id, **common))


def _venue_from_alpaca(asset_class: str | None, exchange: str | None) -> str:
    """Best-effort venue mapping for trade_updates (which don't always
    carry a venue field). Falls back to XNAS.
    """
    if (asset_class or "").lower() == "crypto":
        return "ALPACA_CRYPTO"
    e = (exchange or "").upper()
    return {
        "NASDAQ": "XNAS",
        "OTC": "XNAS",
        "NYSE": "XNYS",
        "AMEX": "XNYS",
        "ARCA": "ARCX",
        "BATS": "BATS",
    }.get(e, "XNAS")


__all__ = [
    "AlpacaTradeUpdatesClient",
    "publish_trade_update_to_bus",
]
