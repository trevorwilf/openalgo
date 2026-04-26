"""Mock Schwab-LIKE stream adapter — in-memory, no network."""

from __future__ import annotations

import uuid
from typing import Any

from domain.broker_streaming import SubscriptionHandle
from domain.enums import StreamTransport

BROKER_CODE = "_mock_schwab_like"


class MockSchwabLikeMarketDataStream:
    broker_code = BROKER_CODE
    transport = StreamTransport.WEBSOCKET

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
            raw_id=f"MOCK-WS-{uuid.uuid4().hex[:8]}",
            metadata={"instruments": [str(i) for i in instruments]},
        )
        if on_quote is not None:
            for i in range(3):
                await on_quote({
                    "symbol": "AAPL",
                    "venue_code": "XNAS",
                    "bid": "150.10",
                    "ask": "150.12",
                    "last": str(150 + i / 100),
                })
        return handle

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        self.unsubscribed_handles.append(handle)


class MockSchwabLikeOrderEventStream:
    broker_code = BROKER_CODE
    transport = StreamTransport.WEBSOCKET

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
            raw_id=f"MOCK-OE-{uuid.uuid4().hex[:8]}",
        )
        if on_order_event is not None:
            await on_order_event({
                "order_id": "MOCK-1",
                "status": "ACCEPTED",
            })
        return handle

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        self.unsubscribed_handles.append(handle)


__all__ = [
    "BROKER_CODE",
    "MockSchwabLikeMarketDataStream",
    "MockSchwabLikeOrderEventStream",
]
