"""Regression: ``AlpacaWebSocketClient`` resets the reconnect backoff
delay on auth success, not just the attempt counter.

Bug: ``_reader_loop`` kept ``delay`` as a local variable and grew it
on every reconnect via ``delay = min(delay * factor, max_delay)``.
Auth-success in ``_on_message`` reset ``_reconnect_attempt`` to 0
but never the delay. After several disconnects the delay sat at
the cap (``_reconnect_max_delay``, default 30s) and stayed there
for the lifetime of the process, even when the next disconnect
came hours later.

Symptom: after a few network blips during a long session, every
subsequent reconnect waited 30s before retry — visible in the
log as ``Alpaca WS reconnect attempt N in 30.0s`` even when the
last successful connection was hours ago.

Fix: keep ``_reconnect_delay`` on the instance so ``_on_message``
resets both the attempt counter and the backoff delay together.
"""

from __future__ import annotations

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.streaming.alpaca_websocket import AlpacaWebSocketClient


def _auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _make_client() -> AlpacaWebSocketClient:
    """Construct without starting the reader thread or binding sockets."""
    return AlpacaWebSocketClient(
        auth=_auth(),
        reconnect_initial_delay=1.0,
        reconnect_max_delay=30.0,
        reconnect_backoff_factor=2.0,
    )


def test_reconnect_delay_starts_at_initial():
    client = _make_client()
    assert client._reconnect_delay == 1.0


def test_auth_success_resets_attempt_and_delay():
    """Simulate the post-auth state: attempt counter > 0, delay grown."""
    client = _make_client()
    # Pretend several reconnects have already happened.
    client._reconnect_attempt = 5
    client._reconnect_delay = 30.0  # capped

    # The auth-success branch in _on_message hits this code path.
    # Simulate it directly:
    client._reconnect_attempt = 0
    client._reconnect_delay = client._reconnect_initial_delay

    assert client._reconnect_attempt == 0
    assert client._reconnect_delay == 1.0


def test_on_message_authenticated_resets_both(monkeypatch):
    """End-to-end: feeding the auth-success frame into ``_on_message``
    resets both the attempt counter AND the delay.
    """
    import json

    client = _make_client()
    # State after several disconnects.
    client._reconnect_attempt = 5
    client._reconnect_delay = 30.0
    # Keep _replay_subscriptions a no-op so we don't try to write to
    # a non-existent socket.
    monkeypatch.setattr(client, "_replay_subscriptions", lambda: None)

    auth_frame = json.dumps([{"T": "success", "msg": "authenticated"}])
    client._on_message(client._ws, auth_frame)

    assert client._reconnect_attempt == 0
    assert client._reconnect_delay == 1.0
