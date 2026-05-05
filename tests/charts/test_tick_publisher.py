"""Phase 4 — tick publisher: broker tick → Valkey within 50ms.

Uses fakeredis for the Valkey backend and a stub broker stream.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

fakeredis = pytest.importorskip("fakeredis")

from services.charts import valkey_client as vc  # noqa: E402
from services.charts.tick_publisher import TickPublisher  # noqa: E402


@pytest.fixture(autouse=True)
def _swap_in_fakeredis():
    client = fakeredis.FakeRedis(decode_responses=True)
    vc.reset_client_for_tests(client)
    yield client
    vc.reset_client_for_tests(None)


class _StubInstrument:
    canonical_symbol = "AAPL"
    broker_symbol = "AAPL"


class _StubStream:
    def __init__(self):
        self.handle = None
        self.subscribed = False
        self._on_quote = None
        self._on_bar = None

    async def subscribe(
        self,
        instruments,
        on_quote=None,
        on_bar=None,
        on_disconnect=None,
        **_kw,
    ):
        self.subscribed = True
        self._on_quote = on_quote
        self._on_bar = on_bar

        class _H:
            broker_code = "test"
            transport = "WEBSOCKET"
            raw_id = "test:AAPL"
            metadata = None

        self.handle = _H()
        return self.handle

    async def unsubscribe(self, handle):
        self.subscribed = False


@pytest.mark.asyncio
async def test_publish_trade_within_50ms_to_valkey(_swap_in_fakeredis):
    client = _swap_in_fakeredis
    pub = TickPublisher()
    stream = _StubStream()

    # Subscribe to the pubsub channel BEFORE we feed a tick — the
    # publisher publishes immediately and we want to verify the message
    # arrives at the channel.
    ps = client.pubsub()
    ps.subscribe(vc.ticks_channel("AAPL"))
    # First message is the subscribe ack; ignore.
    ack = ps.get_message(timeout=1)
    assert ack is not None

    await pub.start(stream=stream, instruments=[_StubInstrument()], timeframes=["1m"])

    t0 = time.perf_counter()
    await stream._on_quote(  # type: ignore[union-attr]
        {"S": "AAPL", "p": 100.5, "s": 10, "t": "2024-01-01T00:00:00.000Z"}
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 50.0, f"publish took {elapsed_ms:.2f}ms (target <50ms)"

    # The pubsub channel should have a published message.
    msg = ps.get_message(timeout=1)
    assert msg is not None
    assert msg.get("type") == "message"
    payload = json.loads(msg["data"])
    assert payload["symbol"] == "AAPL"
    assert payload["payload"]["p"] == 100.5

    await pub.stop()
    ps.close()


@pytest.mark.asyncio
async def test_bar_close_persists_to_tail(_swap_in_fakeredis):
    client = _swap_in_fakeredis
    pub = TickPublisher()
    stream = _StubStream()
    await pub.start(stream=stream, instruments=[_StubInstrument()], timeframes=["1m"])

    # Trade in bucket 0 …
    await stream._on_quote(  # type: ignore[union-attr]
        {"S": "AAPL", "p": 100.0, "s": 10, "t": "2024-01-01T00:00:30.000Z"}
    )
    # … then trade in bucket 1 — closes the prior bucket.
    await stream._on_quote(  # type: ignore[union-attr]
        {"S": "AAPL", "p": 101.0, "s": 5, "t": "2024-01-01T00:01:30.000Z"}
    )

    # Tail must contain at least one closed bar.
    tail = client.lrange(vc.tail_key("AAPL", "1m"), 0, -1)
    assert len(tail) >= 1
    bar = json.loads(tail[0])
    assert bar["o"] == "100.0"
    assert bar["c"] == "100.0"

    await pub.stop()


@pytest.mark.asyncio
async def test_unsubscribe_calls_stream_unsubscribe(_swap_in_fakeredis):
    pub = TickPublisher()
    stream = _StubStream()
    await pub.start(stream=stream, instruments=[_StubInstrument()], timeframes=["1m"])
    await pub.stop()
    assert stream.subscribed is False
