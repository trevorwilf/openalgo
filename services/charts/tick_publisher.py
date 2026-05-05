"""Phase 4 — backend tick publisher.

Subscribes to a registered :class:`BrokerMarketDataStream` (Alpaca in
Phase 4 — D-03) and re-emits ticks to Valkey:

* ``pubsub:ticks:<symbol>`` — JSON tick payload, fanned out to client
  subscribers via :class:`services.charts.ws_fanout.WsFanout`.
* ``bar:forming:<symbol>:<timeframe>`` — single in-progress bar.
* ``bars:tail:<symbol>:<timeframe>`` — rolling N=200 closed bars.

Latency target (HANDOFF Phase 4 §2): tick at Valkey within 50ms.

Bar aggregation runs per (symbol, timeframe) via
:class:`services.charts.bar_aggregator.BarAggregator`.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from time import time as _time
from typing import Any

from services.charts.bar_aggregator import BarAggregator, FormingBar
from services.charts.valkey_client import (
    TAIL_BARS_LENGTH,
    forming_key,
    get_client,
    tail_key,
    ticks_channel,
)
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _Topic:
    symbol: str
    timeframes: frozenset[str]


class TickPublisher:
    """Bridges a BrokerMarketDataStream → Valkey pub/sub + bar caches.

    Lifecycle:

      ``start(stream, instruments, timeframes)``:
        1. Build one BarAggregator per (symbol, timeframe).
        2. Subscribe to the broker stream — on every tick, publish to
           ``pubsub:ticks:<symbol>`` and feed every aggregator for
           that symbol.
        3. on_close handler writes the closed bar to ``bars:tail:*``
           and clears ``bar:forming:*``.

      ``stop()``:
        Tells the broker stream to unsubscribe; force_close any open
        forming bars; release the Valkey connection.
    """

    def __init__(self) -> None:
        self._aggregators: dict[tuple[str, str], BarAggregator] = {}
        # RLock — `_on_forming` / `_on_close` re-enter the lock when
        # called from a `force_close()` invocation that already holds it.
        self._lock = threading.RLock()
        self._handle: Any = None
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._symbols: set[str] = set()

    async def start(
        self,
        stream: Any,
        instruments: Iterable[Any],
        timeframes: Iterable[str],
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = stream
        symbols = [
            getattr(i, "broker_symbol", None) or getattr(i, "canonical_symbol", None)
            for i in instruments
        ]
        symbols = [s for s in symbols if s]
        with self._lock:
            self._symbols.update(symbols)
            for sym in symbols:
                for tf in timeframes:
                    key = (sym, tf)
                    if key not in self._aggregators:
                        agg = BarAggregator(
                            symbol=sym,
                            timeframe=tf,
                            on_forming=self._on_forming,
                            on_close=self._on_close,
                        )
                        self._aggregators[key] = agg

        # Subscribe to the broker stream.
        self._handle = await stream.subscribe(
            instruments=list(instruments),
            on_quote=self._on_quote_async,
            on_bar=self._on_bar_async,
            on_disconnect=self._on_disconnect_async,
        )
        logger.info(
            "tick_publisher started: symbols=%s timeframes=%s",
            sorted(symbols),
            sorted(timeframes),
        )

    async def stop(self) -> None:
        if self._stream and self._handle:
            try:
                await self._stream.unsubscribe(self._handle)
            except Exception:  # noqa: BLE001
                logger.exception("tick_publisher unsubscribe failed")
        # Force-close the aggregators without holding the lock — the
        # `_on_close` callback re-acquires it for the symbol lookup.
        with self._lock:
            aggs = list(self._aggregators.values())
        for agg in aggs:
            try:
                agg.force_close()
            except Exception:  # noqa: BLE001
                logger.exception("aggregator force_close failed")
        with self._lock:
            self._aggregators.clear()
            self._symbols.clear()
        self._handle = None
        self._stream = None

    # ------- broker callbacks (always async; broker adapter trampolines) -------

    async def _on_quote_async(self, payload: dict[str, Any]) -> None:
        """One trade/quote tick from the broker stream."""
        # Alpaca quote/trade: top-of-book. We treat trade prints as
        # the price source for tick-by-tick aggregation; bid/ask
        # quotes are pushed only to pubsub for client-side use.
        symbol = payload.get("S") or payload.get("symbol") or payload.get("sym")
        if not symbol:
            return
        # Publish the raw tick first — every consumer that wants
        # quote depth / bid-ask gets it via pubsub.
        try:
            now_ms = int(_time() * 1000)
            tick = {
                "kind": "trade" if "p" in payload else "quote",
                "symbol": symbol,
                "t": now_ms,
                "payload": payload,
            }
            self._publish_tick(symbol, tick)
        except Exception:  # noqa: BLE001
            logger.exception("publish_tick failed")

        # Trade tick: feed the aggregators.
        if "p" in payload:
            try:
                price = Decimal(str(payload["p"]))
                size = Decimal(str(payload.get("s") or 0))
                ts = int(_parse_ts_seconds(payload.get("t")) or _time())
                with self._lock:
                    targets = [
                        agg
                        for (s, _tf), agg in self._aggregators.items()
                        if s == symbol
                    ]
                for agg in targets:
                    agg.feed_trade(ts, price, size)
            except Exception:  # noqa: BLE001
                logger.exception("aggregator feed_trade failed")

    async def _on_bar_async(self, payload: dict[str, Any]) -> None:
        """A complete bar from the broker (e.g. Alpaca minute bar)."""
        symbol = payload.get("S") or payload.get("symbol")
        if not symbol:
            return
        with self._lock:
            targets = [
                agg
                for (s, _tf), agg in self._aggregators.items()
                if s == symbol
            ]
        bucket_t = int(_parse_ts_seconds(payload.get("t")) or _time())
        norm = {
            "t": bucket_t,
            "o": payload.get("o", 0),
            "h": payload.get("h", 0),
            "l": payload.get("l", 0),
            "c": payload.get("c", 0),
            "v": payload.get("v", 0),
        }
        for agg in targets:
            try:
                agg.feed_bar(norm)
            except Exception:  # noqa: BLE001
                logger.exception("aggregator feed_bar failed")

    async def _on_disconnect_async(self, _err: BaseException | None) -> None:
        # The broker stream's reconnect-with-backoff handles this; the
        # publisher just logs.
        logger.warning("tick_publisher: broker stream disconnected")

    # ------- emit -----------------------------------------------------

    def _on_forming(self, bar: FormingBar) -> None:
        try:
            client = get_client()
        except RuntimeError:
            return
        symbol = self._symbol_for_aggregator(bar)
        if not symbol:
            return
        with self._lock:
            tfs = [tf for (s, tf), _ in self._aggregators.items() if s == symbol]
        for tf in tfs:
            try:
                client.set(forming_key(symbol, tf), json.dumps(bar.to_dict()))
            except Exception:  # noqa: BLE001
                logger.exception("set forming key failed")

    def _on_close(self, bar: FormingBar) -> None:
        try:
            client = get_client()
        except RuntimeError:
            return
        symbol = self._symbol_for_aggregator(bar)
        if not symbol:
            return
        with self._lock:
            tfs = [tf for (s, tf), _ in self._aggregators.items() if s == symbol]
        for tf in tfs:
            try:
                client.delete(forming_key(symbol, tf))
                tail = tail_key(symbol, tf)
                # LPUSH then LTRIM to keep the rolling tail at N=200.
                client.lpush(tail, json.dumps(bar.to_dict()))
                client.ltrim(tail, 0, TAIL_BARS_LENGTH - 1)
            except Exception:  # noqa: BLE001
                logger.exception("close-bar persist failed")

    def _publish_tick(self, symbol: str, tick: dict[str, Any]) -> None:
        try:
            client = get_client()
        except RuntimeError:
            return
        try:
            client.publish(ticks_channel(symbol), json.dumps(tick))
        except Exception:  # noqa: BLE001
            logger.exception("publish tick failed")

    def _symbol_for_aggregator(self, bar: FormingBar) -> str | None:
        # We don't carry symbol on FormingBar; look it up by reverse
        # mapping. The aggregator emits via callbacks so the publisher
        # has the (symbol, tf) key in scope at call-time. This helper
        # is best-effort for forming-bar emission via stored aggs.
        with self._lock:
            for (s, _tf), agg in self._aggregators.items():
                if agg.current is bar:
                    return s
        return None


def _parse_ts_seconds(ts: Any) -> float | None:
    """Best-effort tick-timestamp parser. Alpaca uses RFC-3339 strings;
    other brokers might use epoch ms. Returns UTC seconds (float)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        # Heuristic: ms vs s — anything > 1e12 is ms.
        return float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
    if isinstance(ts, str):
        try:
            from datetime import datetime, timezone

            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                timezone.utc
            ).timestamp()
        except Exception:  # noqa: BLE001
            return None
    return None


__all__ = ["TickPublisher"]
