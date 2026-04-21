"""Shared fixtures for Phase 3c WebSocket tests.

We cannot instantiate `BaseBrokerWebSocketAdapter` directly (it's
abstract and also binds a ZeroMQ socket at construction time). Tests
use the `TestAdapter` subclass below which skips the ZMQ dance entirely
and records the subscribe calls it receives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter


class TestAdapter(BaseBrokerWebSocketAdapter):
    """Minimal concrete adapter. Bypasses the ZMQ-bound base __init__."""

    def __init__(self, broker_code: str = "zerodha") -> None:
        # Deliberately skip super().__init__() so we don't touch ZMQ.
        self.logger = get_logger("test_adapter")
        self.broker_code = broker_code
        self._uses_shared_zmq = False
        self._shared_publisher = None
        self.socket = None
        self.context = None
        self.zmq_port = 0
        self.subscriptions = {}
        self.connected = False
        self._subscribed_instrument_ids = {}

        # Capture everything subscribe() and publish_market_data() see
        self.subscribe_calls: list[tuple] = []
        self.unsubscribe_calls: list[tuple] = []
        self.published: list[tuple[str, dict]] = []

    # Abstract methods

    def initialize(self, broker_name, user_id, auth_data=None):
        return {"status": "success"}

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        self.subscribe_calls.append((symbol, exchange, mode, depth_level))
        return {"status": "success", "symbol": symbol, "exchange": exchange}

    def unsubscribe(self, symbol, exchange, mode=2):
        self.unsubscribe_calls.append((symbol, exchange, mode))
        return {"status": "success"}

    # Override publish to capture rather than send over ZMQ
    def publish_market_data(self, topic, data):
        enriched = self._enrich_outbound_data(data)
        self.published.append((topic, enriched))


@pytest.fixture
def adapter() -> TestAdapter:
    return TestAdapter(broker_code="zerodha")


@pytest.fixture
def instruments_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test SQLite file for the Phase 2a instrument tables."""
    db_file = tmp_path / "phase3c_instruments.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    yield db_file
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def reset_default_resolver():
    from services import instrument_resolver

    instrument_resolver.reset_default_resolver_for_tests()
    yield
    instrument_resolver.reset_default_resolver_for_tests()
