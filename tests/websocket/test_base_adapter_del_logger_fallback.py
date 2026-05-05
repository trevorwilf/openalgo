"""Regression: ``cleanup_zmq`` doesn't crash when ``self.logger`` is
missing (e.g. mid-``__del__`` after Python starts tearing down the
instance ``__dict__``).

Bug: ``broker/alpaca/streaming/alpaca_websocket.py`` (and any other
adapter) sets ``self.logger`` in ``__init__``. Under garbage
collection, ``__del__`` invokes ``cleanup_zmq`` which used
``self.logger.<level>(...)`` — but Python may have already cleared
``self.logger`` by that point, raising::

    AttributeError: 'AlpacaWebSocketAdapter' object has no attribute 'logger'

The destructor's outer ``except`` then swallowed the AttributeError
but the cleanup itself was bypassed (no port release, no instance-
count decrement). Repeated GC cycles flooded ``log/errors.jsonl``.

Fix: ``cleanup_zmq`` reads ``self.logger`` via ``getattr(self,
"logger", logger)`` and uses the module-level ``logger`` as
fallback. Cleanup proceeds normally even mid-destruction.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter


class _FakeAdapter(BaseBrokerWebSocketAdapter):
    """Stub subclass — bypasses ``super().__init__`` (which would bind
    real ZMQ ports) and sets only the attrs ``cleanup_zmq`` reads.
    """

    def initialize(self, broker_name, user_id, auth_data=None): ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def subscribe(self, symbol, exchange, mode=2, depth_level=5): ...
    def unsubscribe(self, symbol, exchange, mode=2): ...


def _build_stub() -> _FakeAdapter:
    """Construct without invoking ``__init__`` so we don't bind ports."""
    adapter = _FakeAdapter.__new__(_FakeAdapter)
    adapter.zmq_port = None
    adapter.socket = None
    adapter._uses_shared_zmq = False
    # Note: deliberately NOT setting ``self.logger`` — that's the
    # state we're regression-testing.
    return adapter


def test_cleanup_zmq_falls_back_to_module_logger_when_self_logger_missing():
    adapter = _build_stub()
    # Cleanup must not raise even though ``self.logger`` is unset.
    adapter.cleanup_zmq()
    # Idempotency — second call is a no-op.
    adapter.cleanup_zmq()


def test_del_does_not_propagate_attribute_error():
    """Ensure ``__del__`` itself never raises into the GC log spam path."""
    adapter = _build_stub()
    # Trigger ``__del__`` explicitly via dunder. It must not raise.
    adapter.__del__()
