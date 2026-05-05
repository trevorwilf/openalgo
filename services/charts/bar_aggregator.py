"""Phase 4 — per-(symbol, timeframe) rolling forming bar.

Consumes normalized ticks (trade prints) and rolls them into a
forming bar at the bucket boundary defined by `intervals_service`.
Emits two signals:

* ``on_forming(bar)`` — bucket is in-progress; price moved.
* ``on_close(bar)``   — bucket boundary crossed; bar is final.

Threading: callers must serialize ticks per (symbol, timeframe). The
class is NOT thread-safe across symbols. The chart workspace's
backend tick publisher runs one aggregator per (symbol, timeframe)
on a single dispatcher thread.

The class is engine-/transport-neutral: it never opens a connection,
never persists. Phase 4 wires Valkey persistence in
``services.charts.tick_publisher``; the aggregator just emits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from services.charts.intervals_service import is_canonical


@dataclass
class FormingBar:
    """In-progress OHLCV bar for a single (symbol, timeframe) bucket."""

    bucket_t: int  # UTC seconds — bucket start
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741
    c: Decimal
    v: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": int(self.bucket_t),
            "o": str(self.o),
            "h": str(self.h),
            "l": str(self.l),
            "c": str(self.c),
            "v": str(self.v),
            "oi": None,
        }


# Bucket sizes for tick→bar aggregation.
_BUCKET_SECONDS: dict[str, int] = {
    "1s": 1,
    "5s": 5,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    # 1mo: calendar-aware. Use month-floor logic via the date adapter.
}


def bucket_size_seconds(timeframe: str) -> int | None:
    """Bucket length in seconds, or None for calendar-aware ('1mo')."""
    return _BUCKET_SECONDS.get(timeframe)


def bucket_start(timeframe: str, ts_seconds: int) -> int:
    """Floor a UTC-seconds timestamp to the bucket start of `timeframe`."""
    size = _BUCKET_SECONDS.get(timeframe)
    if size is None:
        # 1mo — fallback bucket = month start in UTC.
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(int(ts_seconds), tz=timezone.utc)
        return int(
            datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).timestamp()
        )
    return (int(ts_seconds) // size) * size


@dataclass
class BarAggregator:
    """Rolls ticks into a forming bar; emits on_close at bucket
    boundaries. One instance per (symbol, timeframe).
    """

    symbol: str
    timeframe: str
    on_forming: Callable[[FormingBar], None] | None = None
    on_close: Callable[[FormingBar], None] | None = None
    _forming: FormingBar | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not is_canonical(self.timeframe):
            raise ValueError(f"non-canonical timeframe: {self.timeframe!r}")

    def feed_trade(self, ts_seconds: int, price: Decimal, size: Decimal) -> None:
        """Apply a single trade tick to the rolling forming bar.

        - ``ts_seconds`` is UTC seconds (NOT ms — convert at the wire
          boundary so the aggregator stays unit-correct).
        - ``price`` and ``size`` are :class:`decimal.Decimal` — never
          floats — to preserve precision.
        """
        bucket = bucket_start(self.timeframe, ts_seconds)
        if self._forming is None:
            self._forming = FormingBar(
                bucket_t=bucket, o=price, h=price, l=price, c=price, v=size
            )
            self._emit_forming()
            return

        if bucket > self._forming.bucket_t:
            # Bucket boundary crossed. Close the prior bar; open new.
            closed = self._forming
            if self.on_close:
                self.on_close(closed)
            self._forming = FormingBar(
                bucket_t=bucket, o=price, h=price, l=price, c=price, v=size
            )
            self._emit_forming()
            return

        if bucket < self._forming.bucket_t:
            # Late tick from a prior bucket — ignore (downstream pipes
            # handle out-of-order with last-write-wins on `t`).
            return

        # Same bucket — update.
        f = self._forming
        if price > f.h:
            f.h = price
        if price < f.l:
            f.l = price
        f.c = price
        f.v += size
        self._emit_forming()

    def feed_bar(self, raw_bar: dict[str, Any]) -> None:
        """Apply a server-emitted bar (e.g. Alpaca's per-minute close)
        directly. The aggregator treats it as the canonical close for
        the bucket and emits both forming + close.
        """
        bucket = int(raw_bar["t"])
        bar = FormingBar(
            bucket_t=bucket,
            o=Decimal(str(raw_bar["o"])),
            h=Decimal(str(raw_bar["h"])),
            l=Decimal(str(raw_bar["l"])),
            c=Decimal(str(raw_bar["c"])),
            v=Decimal(str(raw_bar.get("v", 0))),
        )
        if self._forming and self._forming.bucket_t < bucket:
            if self.on_close:
                self.on_close(self._forming)
        self._forming = bar
        if self.on_close:
            self.on_close(bar)
        # Then start the next forming = None until next tick.
        self._forming = None

    def force_close(self) -> None:
        """Emit on_close for the current forming bar (if any) without
        waiting for a tick to cross the bucket boundary. Used by the
        publisher when a subscription unsubscribes mid-bucket."""
        if self._forming and self.on_close:
            self.on_close(self._forming)
        self._forming = None

    @property
    def current(self) -> FormingBar | None:
        return self._forming

    def _emit_forming(self) -> None:
        if self._forming and self.on_forming:
            self.on_forming(self._forming)


__all__ = [
    "BarAggregator",
    "FormingBar",
    "bucket_size_seconds",
    "bucket_start",
]
