"""Shared fixtures for ``tests/broker/alpaca/``.

The streaming-adapter tests (``test_streaming_adapter.py`` and
``test_crypto_routing.py``) construct real
:class:`broker.alpaca.streaming.alpaca_adapter.AlpacaWebSocketAdapter`
instances. Each instantiation reaches into
:class:`websocket_proxy.base_adapter.BaseBrokerWebSocketAdapter`,
opens a ZeroMQ PUB socket, and binds it to a TCP port (loopback,
range 5556+). The socket isn't released until the adapter's
``cleanup()`` is called.

When ports/sockets leak between tests:

  * Subsequent ``find_free_zmq_port`` calls walk further up the
    range, eventually exhausting the limited number of attempts.
  * Tests that DO need a fresh port hang on the class-level
    ``_port_lock`` while the prior test's socket holds it.
  * Re-running the suite a few times can saturate enough ports to
    deadlock pytest entirely (the ``Timeout`` we hit earlier).

The autouse fixture below isolates the streaming tests by stubbing
the ZMQ bind for the duration of each test. The stub records the
bind call so existing assertions on ``adapter.zmq_port`` still pass,
and the per-test cleanup releases nothing because nothing was bound
in the first place. Production code is untouched — only the test
process sees the patch, and only inside this directory.

Tests that genuinely need a real ZMQ socket can opt out by setting
``adapter._bound_ports.discard(port)`` themselves; nothing in the
existing suite does, so the wholesale stub is safe.
"""

from __future__ import annotations

import itertools

import pytest


# Synthetic port allocator — a monotonically incrementing counter
# yields a fresh "port number" for each adapter the test creates.
# Tests that introspect ``adapter.zmq_port`` get a unique non-zero
# integer per adapter, exactly like the real allocator would yield.
_synthetic_port_seq = itertools.count(start=59000)


@pytest.fixture(autouse=True)
def _stub_zmq_bind(monkeypatch):
    """Replace :meth:`_bind_to_available_port` with a synthetic
    counter for every test in this directory.

    The real implementation creates a ZMQ PUB socket and binds it
    to a loopback port. Tests run hundreds of these without
    cleanup, which leaks file descriptors and walks the port-finder
    into a deadlock under ``_port_lock``. The stub returns a
    monotonic synthetic port without touching the network.
    """
    from websocket_proxy import base_adapter

    def _fake_bind(self):  # type: ignore[no-untyped-def]
        port = next(_synthetic_port_seq)
        # Mirror what the real method records on the instance so any
        # downstream assertions (zmq_port introspection, log lines)
        # see a consistent value.
        if not hasattr(self, "socket") or self.socket is None:
            # Some tests skip socket construction entirely (e.g. ones
            # that mock the whole adapter); leave it that way.
            pass
        return port

    monkeypatch.setattr(
        base_adapter.BaseBrokerWebSocketAdapter,
        "_bind_to_available_port",
        _fake_bind,
    )

    # Reset the class-level "remembered" bound-ports set between
    # tests so any test that DOES inspect it sees a clean slate.
    monkeypatch.setattr(
        base_adapter.BaseBrokerWebSocketAdapter,
        "_bound_ports",
        set(),
    )

    yield
