"""Mock Webull-LIKE stream adapter — MQTT (market data) + gRPC (orders)."""

from __future__ import annotations

import uuid
from typing import Any

from domain.broker_streaming import SubscriptionHandle
from domain.enums import StreamTransport

BROKER_CODE = "_mock_webull_like"


class MockWebullLikeMarketDataStream:
    broker_code = BROKER_CODE
    transport = StreamTransport.MQTT

    def __init__(self) -> None:
        self.unsubscribed_handles: list[SubscriptionHandle] = []

    async def subscribe(
        self,
        instruments,
        account_ctx,
        on_quote=None,
        on_bar=None,
        on_depth=None,
        on_disconnect=None,
    ) -> SubscriptionHandle:
        handle = SubscriptionHandle(
            broker_code=BROKER_CODE,
            transport=self.transport,
            raw_id=f"MOCK-MQTT-{uuid.uuid4().hex[:8]}",
        )
        if on_quote is not None:
            for i in range(3):
                await on_quote({
                    "symbol": "MSFT",
                    "venue_code": "XNAS",
                    "bid": "400.40",
                    "ask": "400.45",
                    "last": str(400 + i / 100),
                })
        return handle

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        self.unsubscribed_handles.append(handle)


class MockWebullLikeOrderEventStream:
    broker_code = BROKER_CODE
    transport = StreamTransport.GRPC

    def __init__(self) -> None:
        self.unsubscribed_handles: list[SubscriptionHandle] = []

    async def subscribe(
        self,
        account_ctx,
        on_order_event=None,
        on_fill=None,
        on_disconnect=None,
    ) -> SubscriptionHandle:
        handle = SubscriptionHandle(
            broker_code=BROKER_CODE,
            transport=self.transport,
            raw_id=f"MOCK-GRPC-{uuid.uuid4().hex[:8]}",
        )
        if on_order_event is not None:
            await on_order_event({
                "order_id": "MOCK-WEBULL-1",
                "status": "ACCEPTED",
            })
        return handle

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        self.unsubscribed_handles.append(handle)


__all__ = [
    "BROKER_CODE",
    "MockWebullLikeMarketDataStream",
    "MockWebullLikeOrderEventStream",
]
