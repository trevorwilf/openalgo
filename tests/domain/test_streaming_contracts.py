"""Phase 8 — broker streaming protocol contracts."""

from __future__ import annotations

import pytest

from domain.broker_streaming import (
    BrokerMarketDataStream,
    BrokerOrderEventStream,
    NotYetImplementedStream,
    SubscriptionHandle,
)
from domain.enums import StreamTransport
from services.broker_streaming_registry import (
    clear_streaming_registries_for_tests,
    get_market_data_stream,
    get_order_event_stream,
    register_market_data_stream,
    register_order_event_stream,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_streaming_registries_for_tests()
    yield
    clear_streaming_registries_for_tests()


def test_websocket_transport_value() -> None:
    assert StreamTransport.WEBSOCKET.value == "WEBSOCKET"
    assert StreamTransport.MQTT.value == "MQTT"
    assert StreamTransport.GRPC.value == "GRPC"
    assert StreamTransport.SSE.value == "SSE"
    assert StreamTransport.POLL.value == "POLL"


def test_subscription_handle_is_frozen_dataclass() -> None:
    h = SubscriptionHandle(
        broker_code="alpaca",
        transport=StreamTransport.WEBSOCKET,
        raw_id="sub-1",
    )
    with pytest.raises(Exception):
        h.broker_code = "schwab"  # type: ignore[misc]


def test_not_yet_implemented_stream_raises_on_subscribe() -> None:
    s = NotYetImplementedStream("schwab", StreamTransport.WEBSOCKET)
    import asyncio

    async def _exercise():
        with pytest.raises(NotImplementedError):
            await s.subscribe([])

    asyncio.run(_exercise())


def test_market_data_registry_round_trip() -> None:
    class _Fake:
        broker_code = "fake"
        transport = StreamTransport.WEBSOCKET

        async def subscribe(self, *args, **kwargs):
            return SubscriptionHandle("fake", StreamTransport.WEBSOCKET, "x")

        async def unsubscribe(self, handle):
            pass

    fake = _Fake()
    register_market_data_stream(fake)  # type: ignore[arg-type]
    assert get_market_data_stream("fake") is fake
    assert get_market_data_stream("nope") is None


def test_order_event_registry_round_trip() -> None:
    class _Fake:
        broker_code = "fake"
        transport = StreamTransport.GRPC

        async def subscribe(self, *args, **kwargs):
            return SubscriptionHandle("fake", StreamTransport.GRPC, "y")

        async def unsubscribe(self, handle):
            pass

    fake = _Fake()
    register_order_event_stream(fake)  # type: ignore[arg-type]
    assert get_order_event_stream("fake") is fake


def test_broker_market_data_stream_runtime_check() -> None:
    class _Conforms:
        broker_code = "x"
        transport = StreamTransport.WEBSOCKET

        async def subscribe(self, *args, **kwargs):
            return SubscriptionHandle("x", StreamTransport.WEBSOCKET, "1")

        async def unsubscribe(self, handle):
            pass

    assert isinstance(_Conforms(), BrokerMarketDataStream)


def test_broker_order_event_stream_runtime_check() -> None:
    class _Conforms:
        broker_code = "x"
        transport = StreamTransport.SSE

        async def subscribe(self, *args, **kwargs):
            return SubscriptionHandle("x", StreamTransport.SSE, "2")

        async def unsubscribe(self, handle):
            pass

    assert isinstance(_Conforms(), BrokerOrderEventStream)
