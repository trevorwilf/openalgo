"""Phase 4 — ws_fanout multi-client / single-broker-subscription tests."""

from __future__ import annotations

import asyncio

import pytest

from services.charts.ws_fanout import WsFanout


class _CountingPublisher:
    started = 0
    stopped = 0

    async def start(self, *, stream, instruments, timeframes):
        type(self).started += 1
        self._instruments = instruments

    async def stop(self):
        type(self).stopped += 1


class _StubStream:
    pass


def _factory():
    return _CountingPublisher()


async def _stream():
    return _StubStream()


async def _resolver(symbol: str):
    return {"canonical_symbol": symbol}


@pytest.fixture(autouse=True)
def _reset_publisher_state():
    _CountingPublisher.started = 0
    _CountingPublisher.stopped = 0


@pytest.mark.asyncio
async def test_first_acquire_spins_up_publisher_subsequent_does_not():
    fan = WsFanout(_factory, _stream, _resolver)
    await fan.acquire("AAPL", "1m")
    await fan.acquire("AAPL", "5m")
    assert _CountingPublisher.started == 1


@pytest.mark.asyncio
async def test_release_decrements_and_stops_when_zero():
    fan = WsFanout(_factory, _stream, _resolver)
    await fan.acquire("AAPL", "1m")
    await fan.acquire("AAPL", "5m")
    assert _CountingPublisher.started == 1

    await fan.release("AAPL", "5m")
    assert _CountingPublisher.stopped == 0  # still one subscriber

    await fan.release("AAPL", "1m")
    assert _CountingPublisher.stopped == 1


@pytest.mark.asyncio
async def test_release_within_5s_of_last_client():
    fan = WsFanout(_factory, _stream, _resolver)
    await fan.acquire("AAPL", "1m")
    import time

    t0 = time.perf_counter()
    await fan.release("AAPL", "1m")
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_release_unknown_symbol_does_nothing():
    fan = WsFanout(_factory, _stream, _resolver)
    # No publisher should be started or stopped.
    await fan.release("MSFT", "1m")
    assert _CountingPublisher.started == 0
    assert _CountingPublisher.stopped == 0


@pytest.mark.asyncio
async def test_multi_symbol_independent_lifecycles():
    fan = WsFanout(_factory, _stream, _resolver)
    await fan.acquire("AAPL", "1m")
    await fan.acquire("MSFT", "1m")
    assert _CountingPublisher.started == 2
    await fan.release("AAPL", "1m")
    assert _CountingPublisher.stopped == 1
    await fan.release("MSFT", "1m")
    assert _CountingPublisher.stopped == 2
