"""Phase 6 — stream client tests."""
from __future__ import annotations

import threading
import time

import pytest

import bowaka_v2_stream as st


def test_stream_disabled_by_default():
    cfg = st.StreamConfig(enabled=False)
    client = st.StreamClient(cfg, connect_supplier=lambda c: None)
    client.start()
    assert client._thread is None  # never started


def test_stream_reconnect_backoff():
    """Failed connects produce exponential backoff up to the cap."""
    cfg = st.StreamConfig(
        enabled=True, reconnect_initial_backoff_seconds=0.01,
        reconnect_max_backoff_seconds=0.05,
        max_consecutive_failures=10,
    )
    attempts = []
    barrier = threading.Event()

    def supplier(_c):
        attempts.append(time.time())
        if len(attempts) >= 4:
            barrier.set()
        raise RuntimeError("simulated failure")

    client = st.StreamClient(cfg, connect_supplier=supplier)
    client.start()
    barrier.wait(timeout=2.0)
    client.stop()
    # Spacing between attempts should grow up to the cap.
    diffs = [attempts[i + 1] - attempts[i] for i in range(len(attempts) - 1)]
    # Not strict; just verify some non-zero backoff happened.
    assert any(d > 0.01 for d in diffs)


def test_stream_falls_back_to_polling_after_max_failures():
    cfg = st.StreamConfig(
        enabled=True, reconnect_initial_backoff_seconds=0.01,
        reconnect_max_backoff_seconds=0.02,
        max_consecutive_failures=3,
    )

    def supplier(_c):
        raise RuntimeError("always fails")

    client = st.StreamClient(cfg, connect_supplier=supplier)
    client.start()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if client.health.falled_back_to_polling:
            break
        time.sleep(0.02)
    client.stop()
    assert client.health.falled_back_to_polling is True
    assert client.health.consecutive_failures >= cfg.max_consecutive_failures


def test_stream_put_bar_updates_buffer_and_health():
    cfg = st.StreamConfig(enabled=False)
    client = st.StreamClient(cfg, connect_supplier=lambda c: None)
    client.put_bar("AAA", {"close": 10.0, "ts": "x"})
    bars = client.drain()
    assert len(bars) == 1
    assert bars[0][0] == "AAA"
    assert client.health.last_message_at is not None
