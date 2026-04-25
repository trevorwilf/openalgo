# ADR 0014 — Broker streaming + order-event transport contracts

Status: accepted (Phase 8, market-agnostic v2)
Date: 2026-04-25

## Context

OpenAlgo's existing `websocket_proxy/` is the unified market-data
WebSocket server clients connect to (port 8765). Each broker's
adapter publishes ticks into the proxy via a per-broker WebSocket
connection. That pattern works for Indian brokers — they all use
WebSocket — but Schwab and Webull need:

* WebSocket (Schwab Streamer) for quotes / depth.
* MQTT (Webull) for market data — paho-mqtt or aiomqtt under the
  hood.
* gRPC (Webull) for order events.
* SSE (Alpaca paper / live) as a possible future transport.

Without a transport-agnostic streaming contract, every new broker
plugin would invent its own dispatcher.

## Decision

`domain/broker_streaming.py` defines two `Protocol` classes plus a
small data class:

```python
@dataclass(frozen=True)
class SubscriptionHandle:
    broker_code: str
    transport: StreamTransport
    raw_id: str
    metadata: dict[str, Any] | None

class BrokerMarketDataStream(Protocol):
    broker_code: str
    transport: StreamTransport
    async def subscribe(self, instruments, account_ctx,
                        on_quote=None, on_bar=None, on_depth=None,
                        on_disconnect=None) -> SubscriptionHandle: ...
    async def unsubscribe(self, handle) -> None: ...

class BrokerOrderEventStream(Protocol):
    broker_code: str
    transport: StreamTransport
    async def subscribe(self, account_ctx, on_order_event=None,
                        on_fill=None, on_disconnect=None)
                        -> SubscriptionHandle: ...
    async def unsubscribe(self, handle) -> None: ...
```

`StreamTransport` enum values: `WEBSOCKET`, `MQTT`, `GRPC`, `SSE`,
`POLL`.

`services/broker_streaming_registry.py` mirrors the translator
registry: `register_market_data_stream`, `get_market_data_stream`,
`register_order_event_stream`, `get_order_event_stream`. The
registry is empty at import time — Webull MQTT and Schwab streamer
plugins register their concrete classes at startup.

`NotYetImplementedStream` is a placeholder concrete class that
raises `NotImplementedError` on use; useful for feature-flagged
branches that need a typed reference.

## Consequences

* **Per-broker streaming code lives in the broker plugin**, not in
  `websocket_proxy/`. The proxy retains its role for the existing
  Indian-broker pipeline; new plugins implement the Protocol
  directly.
* **Disconnect handling is uniform** — every plugin's stream raises
  through the same `on_disconnect` callback so higher layers can
  retry or notify.
* **Order events are first-class** rather than emerging from polling
  the order-book endpoint.

## Alternatives considered

* **Force everything into WebSocket.** Rejected — Webull's docs make
  MQTT vs gRPC explicit; pretending otherwise would create technical
  debt the day the plugin ships.
* **Implement the streams in the websocket_proxy/.** Rejected —
  proxy already serves a purpose (unified client-facing port);
  layering broker transports there couples concerns.

## References

* `domain/broker_streaming.py`
* `services/broker_streaming_registry.py`
* `tests/domain/test_streaming_contracts.py`
* `docs/refactor/schwab_readiness.md`
* `docs/refactor/webull_readiness.md`
