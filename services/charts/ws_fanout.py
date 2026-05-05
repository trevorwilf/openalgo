"""Phase 4 — single broker subscription, multiplexed to N clients.

Maintains a per-symbol broker subscription count: when the first
client subscribes, ``ensure_running(symbol)`` triggers the
:class:`TickPublisher` to start that symbol's stream. When the last
client unsubscribes, ``release(symbol)`` stops the publisher within
5s (HANDOFF §13.2 acceptance #6).

The fan-out reads from Valkey's ``pubsub:ticks:<symbol>`` channel and
writes envelopes to client websockets per the §0.5 contract. Each
connected client gets its own subscriber loop; cross-symbol routing
uses Valkey's pattern subscribe so we don't open one connection per
client × symbol.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from services.charts.valkey_client import get_client, ticks_channel
from services.charts.ws_envelope import WSEnvelope, make_ack
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _SymbolEntry:
    """Bookkeeping for one upstream broker subscription."""

    refcount: int = 0
    publisher: Any | None = None
    timeframes: set[str] = field(default_factory=set)


class WsFanout:
    """Backend WebSocket fan-out for the chart workspace.

    Public surface:

    * ``acquire(symbol, timeframe)`` — increment refcount; spin up the
      backend tick publisher when refcount transitions 0→1.
    * ``release(symbol, timeframe)`` — decrement refcount; tear down
      the publisher when refcount returns to 0. Release fires within
      5s per the streaming-reconnect test suite contract.
    * ``client_iter(symbol)`` — async iterator yielding WSEnvelope
      objects derived from Valkey's ``pubsub:ticks:<symbol>`` channel.
    """

    def __init__(
        self,
        publisher_factory: Callable[[], Any],
        stream_provider: Callable[[], Awaitable[Any]],
        instrument_resolver: Callable[[str], Awaitable[Any]],
    ) -> None:
        """
        - ``publisher_factory()`` — returns a fresh TickPublisher.
        - ``stream_provider()`` — async resolver for the active broker's
          BrokerMarketDataStream (from the streaming registry).
        - ``instrument_resolver(symbol)`` — async resolver from canonical
          symbol → InstrumentRef for the active broker.
        """
        self._publisher_factory = publisher_factory
        self._stream_provider = stream_provider
        self._instrument_resolver = instrument_resolver
        self._entries: dict[str, _SymbolEntry] = {}
        self._lock = threading.Lock()

    async def acquire(self, symbol: str, timeframe: str) -> None:
        spin_up = False
        with self._lock:
            entry = self._entries.get(symbol)
            if entry is None:
                entry = _SymbolEntry()
                self._entries[symbol] = entry
                spin_up = True
            entry.refcount += 1
            entry.timeframes.add(timeframe)
        if spin_up:
            try:
                await self._spin_up(symbol, entry)
            except Exception:  # noqa: BLE001
                logger.exception("ws_fanout spin_up failed for %s", symbol)
                with self._lock:
                    entry.refcount = max(0, entry.refcount - 1)

    async def release(self, symbol: str, timeframe: str) -> None:
        spin_down = False
        with self._lock:
            entry = self._entries.get(symbol)
            if entry is None:
                return
            entry.refcount = max(0, entry.refcount - 1)
            entry.timeframes.discard(timeframe)
            if entry.refcount == 0:
                spin_down = True
                self._entries.pop(symbol, None)
        if spin_down and entry.publisher is not None:
            try:
                await asyncio.wait_for(entry.publisher.stop(), timeout=5.0)
            except Exception:  # noqa: BLE001
                logger.exception("ws_fanout release stop failed")

    async def _spin_up(self, symbol: str, entry: _SymbolEntry) -> None:
        stream = await self._stream_provider()
        if stream is None:
            return
        instrument = await self._instrument_resolver(symbol)
        if instrument is None:
            return
        publisher = self._publisher_factory()
        await publisher.start(
            stream=stream,
            instruments=[instrument],
            timeframes=list(entry.timeframes) or ["1m"],
        )
        entry.publisher = publisher

    async def client_iter(self, symbol: str):
        """Async iterator yielding WSEnvelope dicts as ticks arrive."""
        try:
            client = get_client()
        except RuntimeError:
            return
        ps = client.pubsub()
        ps.subscribe(ticks_channel(symbol))
        try:
            while True:
                msg = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: ps.get_message(timeout=1.0)
                )
                if msg is None:
                    continue
                if msg.get("type") != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except Exception:  # noqa: BLE001
                    continue
                env = WSEnvelope(
                    type="bar_update" if payload.get("kind") == "trade" else "bar_update",
                    subscription_id=symbol,
                    payload=payload,
                )
                yield env
        finally:
            try:
                ps.unsubscribe(ticks_channel(symbol))
                ps.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["WsFanout", "make_ack"]
