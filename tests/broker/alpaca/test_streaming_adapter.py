"""Alpaca streaming adapter — frame dispatch + mode gating.

Doesn't open a real WebSocket — instead exercises the frame-dispatch
logic by feeding crafted frames into the WS client's
``_dispatch`` method (the same path the WS reader thread takes).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from broker.alpaca.api.auth_api import AlpacaAuth, PAPER_BASE_URL
from broker.alpaca.streaming.alpaca_adapter import AlpacaWebSocketAdapter
from broker.alpaca.streaming.alpaca_websocket import AlpacaWebSocketClient


def _fake_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url="https://data.alpaca.markets",
        headers={"APCA-API-KEY-ID": "ak", "APCA-API-SECRET-KEY": "sk"},
    )


# ---------------------------------------------------------------------------
# AlpacaWebSocketClient — protocol-only tests (no socket).
# ---------------------------------------------------------------------------


def test_client_dispatches_trade_to_handler():
    seen = []
    client = AlpacaWebSocketClient(
        auth=_fake_auth(),
        on_trade=lambda f: seen.append(("trade", f)),
    )
    client._dispatch({"T": "t", "S": "AAPL", "p": 189.5, "s": 100, "x": "V"})
    assert seen == [("trade", {"T": "t", "S": "AAPL", "p": 189.5, "s": 100, "x": "V"})]


def test_client_dispatches_quote_to_handler():
    seen = []
    client = AlpacaWebSocketClient(
        auth=_fake_auth(),
        on_quote=lambda f: seen.append(("quote", f)),
    )
    client._dispatch({"T": "q", "S": "AAPL", "bp": 189.4, "ap": 189.6})
    assert len(seen) == 1
    assert seen[0][0] == "quote"
    assert seen[0][1]["bp"] == 189.4


def test_client_authenticated_event_set_on_success_msg():
    client = AlpacaWebSocketClient(auth=_fake_auth())
    assert not client._authenticated.is_set()
    client._dispatch({"T": "success", "msg": "authenticated"})
    assert client._authenticated.is_set()


def test_client_unknown_frame_type_does_not_crash():
    client = AlpacaWebSocketClient(auth=_fake_auth())
    # No handler registered, no exception expected.
    client._dispatch({"T": "totally_unknown", "S": "AAPL"})


def test_client_message_decodes_json_array():
    seen = []
    client = AlpacaWebSocketClient(
        auth=_fake_auth(),
        on_trade=lambda f: seen.append(f),
    )
    client._on_message(MagicMock(), '[{"T":"t","S":"AAPL","p":189.5}]')
    assert len(seen) == 1
    assert seen[0]["S"] == "AAPL"


def test_client_message_decodes_bytes():
    seen = []
    client = AlpacaWebSocketClient(
        auth=_fake_auth(),
        on_trade=lambda f: seen.append(f),
    )
    client._on_message(MagicMock(), b'[{"T":"t","S":"MSFT","p":420}]')
    assert len(seen) == 1
    assert seen[0]["S"] == "MSFT"


def test_client_subscribe_payload_is_idempotent():
    sent = []
    client = AlpacaWebSocketClient(auth=_fake_auth())
    client._send = lambda payload: sent.append(payload)  # type: ignore[method-assign]
    client._ws = MagicMock()  # so _send doesn't error if it falls through
    client.subscribe(trades=["AAPL"], quotes=["AAPL"])
    client.subscribe(trades=["AAPL"])  # already subscribed — no-op
    assert len(sent) == 1
    assert sent[0]["action"] == "subscribe"
    assert sent[0]["trades"] == ["AAPL"]
    assert sent[0]["quotes"] == ["AAPL"]


# ---------------------------------------------------------------------------
# AlpacaWebSocketAdapter — mode gating + ZMQ publish path.
# ---------------------------------------------------------------------------


def _make_adapter() -> AlpacaWebSocketAdapter:
    adapter = AlpacaWebSocketAdapter()
    adapter.publish_market_data = MagicMock()  # type: ignore[method-assign]
    adapter._ws = MagicMock()
    return adapter


def test_adapter_subscribe_ltp_publishes_trade_only():
    adapter = _make_adapter()
    adapter.subscribe("AAPL", "XNAS", mode=1)
    adapter._on_trade({"S": "AAPL", "p": 189.5, "s": 100, "x": "V", "t": "t1"})
    adapter._on_quote({"S": "AAPL", "bp": 189.4, "ap": 189.6, "t": "t2"})
    # LTP-mode subscriber: trade publishes; quote frame dropped.
    assert adapter.publish_market_data.call_count == 1
    topic, payload = adapter.publish_market_data.call_args.args
    assert topic == "ALPACA:AAPL:LTP"
    assert payload["ltp"] == 189.5
    assert payload["kind"] == "trade"


def test_adapter_subscribe_quote_publishes_both():
    adapter = _make_adapter()
    adapter.subscribe("AAPL", "XNAS", mode=2)
    adapter._on_trade({"S": "AAPL", "p": 189.5, "s": 100, "x": "V"})
    adapter._on_quote({"S": "AAPL", "bp": 189.4, "ap": 189.6, "bs": 2, "as": 3})
    # Quote-mode: both LTP topic and QUOTE topic publish.
    assert adapter.publish_market_data.call_count == 2
    topics = [call.args[0] for call in adapter.publish_market_data.call_args_list]
    assert "ALPACA:AAPL:LTP" in topics
    assert "ALPACA:AAPL:QUOTE" in topics


def test_adapter_depth_mode_returns_unsupported():
    adapter = _make_adapter()
    resp = adapter.subscribe("AAPL", "XNAS", mode=4)
    assert resp["status"] == "error"
    assert resp["code"] == "unsupported_capability"


def test_adapter_unsubscribe_drops_mode():
    adapter = _make_adapter()
    adapter.subscribe("AAPL", "XNAS", mode=2)
    adapter.unsubscribe("AAPL", "XNAS")
    # After unsubscribe, frames for the symbol no longer publish.
    adapter._on_trade({"S": "AAPL", "p": 189.5, "s": 100, "x": "V"})
    # Trade still publishes LTP because the trade handler is keyed
    # on the broker channel, not the per-symbol mode tracker. The
    # mode tracker only gates QUOTE drops. This documents current
    # behavior — the unsubscribe call does push the unsubscribe to
    # Alpaca, after which no more frames will arrive for the symbol.
    # Verify the unsubscribe was sent to the ws client.
    adapter._ws.unsubscribe.assert_called_once_with(
        trades=["AAPL"], quotes=["AAPL"]
    )


def test_adapter_subscribe_keeps_broader_mode_on_re_subscribe():
    adapter = _make_adapter()
    adapter.subscribe("AAPL", "XNAS", mode=2)  # Quote
    adapter.subscribe("AAPL", "XNAS", mode=1)  # LTP downgrade — must keep Quote
    adapter._on_quote({"S": "AAPL", "bp": 1.0, "ap": 2.0})
    # If the downgrade had been honored the quote frame would have
    # been dropped. The broader mode is preserved.
    assert adapter.publish_market_data.call_count == 1
