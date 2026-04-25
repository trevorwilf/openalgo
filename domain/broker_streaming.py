"""Phase 8 — broker streaming + order-event transport contracts.

Provides Protocols that future broker plugins implement to ship
real-time market data (Webull MQTT, Schwab WebSocket) and live
order-event streams (Webull gRPC, Schwab streamer, Alpaca SSE).

Protocols are intentionally async — `subscribe` returns a
``SubscriptionHandle`` the caller stores so a later
``unsubscribe(handle)`` can tear the stream down without leaking
connections.

This module ships **Protocols only**. The concrete adapter
implementations live in their own broker plugins (Webull MQTT, Schwab
WebSocket); until a real plugin lands, the registry in
``services.broker_streaming_registry`` stays empty. A stub class
:class:`NotYetImplementedStream` is provided so demonstration code can
import "a" stream type without waiting on a real adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Protocol, runtime_checkable

from domain.enums import StreamTransport
from domain.instrument_ref import InstrumentRef


@dataclass(frozen=True)
class SubscriptionHandle:
    """Opaque handle returned by ``subscribe`` — pass back to ``unsubscribe``.

    The shape carries enough information for the adapter to reconnect
    or replay the subscription on a transient disconnect, but callers
    treat it as opaque.
    """

    broker_code: str
    transport: StreamTransport
    raw_id: str
    metadata: dict[str, Any] | None = None


# Callback aliases — concrete shapes are intentionally loose so adapter
# implementations can carry broker-native fields when needed.
QuoteCallback = Callable[[dict[str, Any]], Awaitable[None]]
BarCallback = Callable[[dict[str, Any]], Awaitable[None]]
DepthCallback = Callable[[dict[str, Any]], Awaitable[None]]
DisconnectCallback = Callable[[BaseException | None], Awaitable[None]]
OrderEventCallback = Callable[[dict[str, Any]], Awaitable[None]]
FillCallback = Callable[[dict[str, Any]], Awaitable[None]]


@runtime_checkable
class BrokerMarketDataStream(Protocol):
    """Real-time market-data stream contract.

    Implementations connect to the broker's quote/depth feed (WebSocket,
    MQTT, gRPC, SSE, or polling) and dispatch to the supplied callbacks.
    """

    broker_code: str
    transport: StreamTransport

    async def subscribe(
        self,
        instruments: Iterable[InstrumentRef],
        account_ctx: Any,
        on_quote: QuoteCallback | None = None,
        on_bar: BarCallback | None = None,
        on_depth: DepthCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
    ) -> SubscriptionHandle: ...

    async def unsubscribe(self, handle: SubscriptionHandle) -> None: ...


@runtime_checkable
class BrokerOrderEventStream(Protocol):
    """Live order-event stream contract.

    Brokers expose order updates (NEW, PARTIALLY_FILLED, FILLED,
    CANCELLED, REJECTED) and per-fill prints over a streaming channel.
    Webull uses gRPC; Schwab uses its streamer; Alpaca uses SSE.
    """

    broker_code: str
    transport: StreamTransport

    async def subscribe(
        self,
        account_ctx: Any,
        on_order_event: OrderEventCallback | None = None,
        on_fill: FillCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
    ) -> SubscriptionHandle: ...

    async def unsubscribe(self, handle: SubscriptionHandle) -> None: ...


class NotYetImplementedStream:
    """Placeholder stream that raises ``NotImplementedError`` on use.

    Useful as a typed placeholder in feature-flagged branches that
    plan to wire a real adapter later.
    """

    def __init__(self, broker_code: str, transport: StreamTransport) -> None:
        self.broker_code = broker_code
        self.transport = transport

    async def subscribe(self, *args: Any, **kwargs: Any) -> SubscriptionHandle:
        raise NotImplementedError(
            f"{type(self).__name__} for {self.broker_code!r} via "
            f"{self.transport.value} not yet implemented"
        )

    async def unsubscribe(self, handle: SubscriptionHandle) -> None:
        raise NotImplementedError


__all__ = [
    "BarCallback",
    "BrokerMarketDataStream",
    "BrokerOrderEventStream",
    "DepthCallback",
    "DisconnectCallback",
    "FillCallback",
    "NotYetImplementedStream",
    "OrderEventCallback",
    "QuoteCallback",
    "SubscriptionHandle",
]
