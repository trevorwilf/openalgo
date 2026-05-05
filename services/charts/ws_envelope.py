"""Phase 1 — Datafeed Foundation: WebSocket envelope contract.

Server-side mirror of ``frontend/src/charts/types/wsEnvelope.ts``.

The envelope wraps every server → client message pushed over the
``/api/v2/streaming`` channel:

    {
      "type": "<EnvelopeType>",
      "subscription_id": "<server-assigned id>",
      "ts": <UTC milliseconds>,
      "payload": <type-dependent>,
    }

Client → server control messages use the same JSON channel:

    {"op": "subscribe", "channel": "...", "last_seen_ts": ..., "params": {...}}
    {"op": "unsubscribe", "subscription_id": "..."}
    {"op": "heartbeat", "client_ts": ...}

This module is engine-/transport-neutral: it does NOT hold a websocket
connection; it just defines the shapes and provides round-trip helpers
the ws_fanout (Phase 4) builds on.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from time import time as _time
from typing import Any, Literal

# Heartbeat interval in milliseconds — must match the client.
HEARTBEAT_INTERVAL_MS = 30_000

EnvelopeType = Literal[
    "bar_update",
    "bar_close",
    "indicator_update",
    "order_update",
    "position_update",
    "trade_event",
    "strategy_signal",
    "ack",
    "error",
]


def _now_ms() -> int:
    return int(_time() * 1000)


@dataclass(frozen=True)
class WSEnvelope:
    """Server → client envelope."""

    type: EnvelopeType
    subscription_id: str
    payload: Any
    ts: int = field(default_factory=_now_ms)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), default=str)

    @classmethod
    def from_json(cls, s: str) -> WSEnvelope:
        raw = json.loads(s)
        return cls(
            type=raw["type"],
            subscription_id=raw.get("subscription_id", ""),
            ts=int(raw.get("ts", _now_ms())),
            payload=raw.get("payload"),
        )


@dataclass(frozen=True)
class WSSubscribe:
    op: Literal["subscribe"] = "subscribe"
    channel: str = ""
    last_seen_ts: int | None = None
    params: dict[str, Any] | None = None


@dataclass(frozen=True)
class WSUnsubscribe:
    op: Literal["unsubscribe"] = "unsubscribe"
    subscription_id: str = ""


@dataclass(frozen=True)
class WSHeartbeat:
    op: Literal["heartbeat"] = "heartbeat"
    client_ts: int = 0


def parse_control(s: str) -> WSSubscribe | WSUnsubscribe | WSHeartbeat:
    """Parse a client → server control message."""
    raw = json.loads(s)
    op = raw.get("op")
    if op == "subscribe":
        return WSSubscribe(
            channel=raw.get("channel", ""),
            last_seen_ts=raw.get("last_seen_ts"),
            params=raw.get("params"),
        )
    if op == "unsubscribe":
        return WSUnsubscribe(subscription_id=raw.get("subscription_id", ""))
    if op == "heartbeat":
        return WSHeartbeat(client_ts=int(raw.get("client_ts", 0)))
    raise ValueError(f"unknown control op: {op!r}")


def make_ack(subscription_id: str, **fields: Any) -> WSEnvelope:
    """Helper for synthesizing an `ack` envelope."""
    return WSEnvelope(type="ack", subscription_id=subscription_id, payload=fields or {})


def make_error(subscription_id: str, code: str, message: str, **details: Any) -> WSEnvelope:
    """Helper for synthesizing an `error` envelope."""
    return WSEnvelope(
        type="error",
        subscription_id=subscription_id,
        payload={"code": code, "message": message, "details": details or None},
    )


__all__ = [
    "HEARTBEAT_INTERVAL_MS",
    "EnvelopeType",
    "WSEnvelope",
    "WSHeartbeat",
    "WSSubscribe",
    "WSUnsubscribe",
    "make_ack",
    "make_error",
    "parse_control",
]
