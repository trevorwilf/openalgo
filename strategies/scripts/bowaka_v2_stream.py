#!/usr/bin/env python3
"""Bowaka v2 — streaming minute-bar ingestion (scaffold).

Subscribes to Alpaca's minute-bar stream and writes bars to an
in-memory ring buffer the scanner can consume directly. Falls back
to polling when the stream disconnects.

Ships ``cfg.data.streaming.enabled = false`` until the operator
validates it.

This module is a scaffold — it exposes the connection-management
contract (reconnect backoff, max consecutive failures, lag
warning thresholds) and a fake transport for tests. The actual
Alpaca client wiring lands later when the operator subscribes to
SIP. Until then, the scanner's polling path stays load-bearing.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


LOG = logging.getLogger("bowaka_v2_stream")


@dataclass
class StreamConfig:
    enabled: bool = False
    reconnect_initial_backoff_seconds: float = 1.0
    reconnect_max_backoff_seconds: float = 30.0
    max_consecutive_failures: int = 5
    lag_warning_seconds: float = 5.0
    lag_severe_seconds: float = 30.0


@dataclass
class StreamHealth:
    last_message_at: datetime | None = None
    consecutive_failures: int = 0
    reconnect_count: int = 0
    falled_back_to_polling: bool = False


class StreamClient:
    """Threaded stream client. ``connect_supplier`` is the injection
    point — it is called repeatedly and is expected to call
    ``put_bar(symbol, bar_dict)`` for each incoming message. On
    exception it raises; the wrapper handles reconnect with
    exponential backoff.
    """

    def __init__(
        self, cfg: StreamConfig,
        *, connect_supplier: Callable[["StreamClient"], None],
    ):
        self.cfg = cfg
        self._connect = connect_supplier
        self._buffer: deque[tuple[str, dict]] = deque(maxlen=10_000)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.health = StreamHealth()
        self._thread: threading.Thread | None = None

    def put_bar(self, symbol: str, bar: dict) -> None:
        with self._lock:
            self._buffer.append((symbol, bar))
            self.health.last_message_at = datetime.now(timezone.utc)
            self.health.consecutive_failures = 0

    def drain(self) -> list[tuple[str, dict]]:
        with self._lock:
            out = list(self._buffer)
            self._buffer.clear()
        return out

    def start(self) -> None:
        if not self.cfg.enabled:
            LOG.info("stream disabled by config; not starting")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="bowaka-v2-stream", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        backoff = self.cfg.reconnect_initial_backoff_seconds
        while not self._stop.is_set():
            try:
                self._connect(self)
                backoff = self.cfg.reconnect_initial_backoff_seconds
            except Exception as e:
                self.health.consecutive_failures += 1
                self.health.reconnect_count += 1
                LOG.warning(
                    "stream connect failed (#%d): %s",
                    self.health.consecutive_failures, e,
                )
                if self.health.consecutive_failures >= self.cfg.max_consecutive_failures:
                    LOG.error(
                        "stream exceeded max_consecutive_failures=%d; "
                        "falling back to polling",
                        self.cfg.max_consecutive_failures,
                    )
                    self.health.falled_back_to_polling = True
                    break
                self._stop.wait(timeout=backoff)
                backoff = min(
                    backoff * 2, self.cfg.reconnect_max_backoff_seconds,
                )

    def lag_seconds(self, now: datetime | None = None) -> float | None:
        if self.health.last_message_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - self.health.last_message_at).total_seconds()
