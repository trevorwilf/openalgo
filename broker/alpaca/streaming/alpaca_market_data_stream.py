"""Phase 4 (Premier Charting) — Alpaca BrokerMarketDataStream impl.

Concrete implementation of :class:`domain.broker_streaming.BrokerMarketDataStream`
wrapping the existing :class:`AlpacaWebSocketClient`. Promotes Alpaca to
the first non-India streaming broker (per HANDOFF D-03).

The underlying ``AlpacaWebSocketClient`` already ships reconnect-with-
backoff; this adapter exposes it through the typed `BrokerMarketDataStream`
contract that the chart workspace's tick publisher consumes.

Threading model — the client runs an `asyncio` -> `threading` bridge:
* ``subscribe()`` runs the synchronous WebSocket connection on a daemon
  thread, then returns a `SubscriptionHandle` once auth completes.
* The on-tick callback is invoked from the WS reader thread; we trampoline
  it onto the calling event loop via ``asyncio.run_coroutine_threadsafe``.
* ``unsubscribe(handle)`` closes the socket cleanly; the daemon thread
  exits within 5s per the streaming reconnect test suite contract.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from typing import Any

from broker.alpaca.api.auth_api import AlpacaAuth
from broker.alpaca.streaming.alpaca_websocket import (
    AlpacaWebSocketClient,
    CRYPTO_FEED_URL,
    DEFAULT_FEED_URL,
)
from domain.broker_streaming import (
    BarCallback,
    BrokerMarketDataStream,
    DepthCallback,
    DisconnectCallback,
    QuoteCallback,
    SubscriptionHandle,
)
from domain.enums import StreamTransport
from domain.instrument_ref import InstrumentRef
from utils.logging import get_logger

logger = get_logger(__name__)


class AlpacaMarketDataStream(BrokerMarketDataStream):
    """Alpaca BrokerMarketDataStream concrete impl."""

    broker_code: str = "alpaca"
    transport: StreamTransport = StreamTransport.WEBSOCKET

    def __init__(self, auth: AlpacaAuth | None = None) -> None:
        self._auth = auth
        self._clients: dict[str, _RunningClient] = {}
        self._lock = threading.Lock()

    async def subscribe(
        self,
        instruments: Iterable[InstrumentRef],
        account_ctx: Any = None,
        on_quote: QuoteCallback | None = None,
        on_bar: BarCallback | None = None,
        on_depth: DepthCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
    ) -> SubscriptionHandle:
        del on_depth, account_ctx  # unused (Alpaca exposes top-of-book only)

        symbols = _instruments_to_symbols(instruments)
        crypto = any("/" in s or s.endswith("USD") and len(s) <= 5 for s in symbols)
        feed_url = CRYPTO_FEED_URL if crypto else DEFAULT_FEED_URL

        loop = asyncio.get_running_loop()

        def _trampoline(coro_factory):
            """Hop off the WS reader thread to the caller's event loop."""

            def _inner(payload: dict[str, Any]) -> None:
                fut = asyncio.run_coroutine_threadsafe(coro_factory(payload), loop)
                fut.result(timeout=5)

            return _inner

        on_trade_cb = _trampoline(on_quote) if on_quote else None
        on_bar_cb = _trampoline(on_bar) if on_bar else None

        def _disc(_msg: str, ctx: dict[str, Any]) -> None:
            if on_disconnect is None:
                return
            err = ctx.get("error")
            asyncio.run_coroutine_threadsafe(on_disconnect(err), loop)

        client = AlpacaWebSocketClient(
            auth=self._auth,
            feed_url=feed_url,
            on_trade=on_trade_cb,
            on_quote=on_trade_cb,
            on_bar=on_bar_cb,
            on_status=_disc if on_disconnect else None,
        )
        # ``start()`` blocks until the auth handshake completes or
        # raises TimeoutError. The reader thread persists across
        # reconnects (exponential backoff handled inside the client).
        client.start(timeout=10)
        client.subscribe(trades=symbols, quotes=symbols, bars=symbols)

        raw_id = f"alpaca:{','.join(sorted(symbols))}"
        with self._lock:
            self._clients[raw_id] = _RunningClient(client)
        return SubscriptionHandle(
            broker_code=self.broker_code,
            transport=self.transport,
            raw_id=raw_id,
            metadata={"feed_url": feed_url, "symbols": list(symbols)},
        )

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        with self._lock:
            running = self._clients.pop(handle.raw_id, None)
        if running is None:
            return
        try:
            running.client.stop()
        except Exception:  # noqa: BLE001
            logger.exception("alpaca-md-stream stop failed")


class _RunningClient:
    """Sentinel for a started client. Holds a strong reference so the
    daemon thread isn't garbage-collected before we explicitly stop it.
    """

    __slots__ = ("client",)

    def __init__(self, client: AlpacaWebSocketClient) -> None:
        self.client = client


def _instruments_to_symbols(refs: Iterable[InstrumentRef]) -> list[str]:
    out: list[str] = []
    for r in refs:
        s = getattr(r, "broker_symbol", None) or getattr(r, "canonical_symbol", None)
        if s:
            out.append(str(s))
    return out


def register() -> None:
    """Register the Alpaca BrokerMarketDataStream with the streaming
    registry. Called by the broker plugin loader at startup if
    ``API_V2_ALPACA=1``.
    """
    from services.broker_streaming_registry import register_market_data_stream

    register_market_data_stream(AlpacaMarketDataStream())
    logger.info("Alpaca BrokerMarketDataStream registered")


__all__ = ["AlpacaMarketDataStream", "register"]
