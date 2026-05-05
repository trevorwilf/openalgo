"""Phase 1 — WebSocket envelope round-trip + control parsing."""

from __future__ import annotations

import json

import pytest

from services.charts.ws_envelope import (
    HEARTBEAT_INTERVAL_MS,
    WSEnvelope,
    WSHeartbeat,
    WSSubscribe,
    WSUnsubscribe,
    make_ack,
    make_error,
    parse_control,
)


def test_envelope_round_trip():
    env = WSEnvelope(
        type="bar_update",
        subscription_id="sub-123",
        payload={"symbol": "AAPL", "bar": {"t": 1700000000, "c": "100.0"}},
    )
    encoded = env.to_json()
    decoded = WSEnvelope.from_json(encoded)
    assert decoded.type == "bar_update"
    assert decoded.subscription_id == "sub-123"
    assert decoded.payload["symbol"] == "AAPL"
    assert decoded.ts == env.ts


def test_envelope_default_ts_is_set():
    env = WSEnvelope(type="ack", subscription_id="x", payload={})
    assert env.ts > 0


def test_make_ack_returns_ack_envelope():
    env = make_ack("sub-1", granted=True)
    assert env.type == "ack"
    assert env.subscription_id == "sub-1"
    assert env.payload == {"granted": True}


def test_make_error_returns_error_envelope():
    env = make_error("sub-1", "subscribe_failed", "broker rejected", reason="auth")
    assert env.type == "error"
    body = env.payload
    assert body["code"] == "subscribe_failed"
    assert body["message"] == "broker rejected"
    assert body["details"] == {"reason": "auth"}


def test_parse_subscribe_with_resume_hook():
    raw = json.dumps({
        "op": "subscribe",
        "channel": "bars:AAPL:1m",
        "last_seen_ts": 1700000000000,
        "params": {"interval": "1m"},
    })
    msg = parse_control(raw)
    assert isinstance(msg, WSSubscribe)
    assert msg.channel == "bars:AAPL:1m"
    assert msg.last_seen_ts == 1700000000000
    assert msg.params == {"interval": "1m"}


def test_parse_unsubscribe():
    raw = json.dumps({"op": "unsubscribe", "subscription_id": "sub-7"})
    msg = parse_control(raw)
    assert isinstance(msg, WSUnsubscribe)
    assert msg.subscription_id == "sub-7"


def test_parse_heartbeat():
    raw = json.dumps({"op": "heartbeat", "client_ts": 1700000000123})
    msg = parse_control(raw)
    assert isinstance(msg, WSHeartbeat)
    assert msg.client_ts == 1700000000123


def test_parse_unknown_op_raises():
    with pytest.raises(ValueError):
        parse_control(json.dumps({"op": "panic"}))


def test_heartbeat_interval_constant():
    assert HEARTBEAT_INTERVAL_MS == 30_000
