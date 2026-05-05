"""Phase 1 — Valkey/Redis client helpers.

Uses ``fakeredis`` as a stand-in so the test runs without a real Valkey
server. Verifies key-prefix constants, TTL semantics, and pubsub
channel names.
"""

from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")

from services.charts import valkey_client as vc  # noqa: E402


@pytest.fixture(autouse=True)
def _swap_in_fakeredis():
    client = fakeredis.FakeRedis(decode_responses=True)
    vc.reset_client_for_tests(client)
    yield client
    vc.reset_client_for_tests(None)


def test_key_prefix_constants():
    assert vc.KEY_PREFIX_HIST == "bars:hist"
    assert vc.KEY_PREFIX_TAIL == "bars:tail"
    assert vc.KEY_PREFIX_FORMING == "bar:forming"
    assert vc.PUBSUB_CHANNEL_PREFIX == "pubsub:ticks"


def test_hist_key_format():
    assert vc.hist_key("AAPL", "1m", 100, 200) == "bars:hist:AAPL:1m:100:200"


def test_tail_and_forming_keys():
    assert vc.tail_key("AAPL", "5m") == "bars:tail:AAPL:5m"
    assert vc.forming_key("AAPL", "5m") == "bar:forming:AAPL:5m"


def test_ticks_channel():
    assert vc.ticks_channel("AAPL") == "pubsub:ticks:AAPL"


def test_hist_ttl_constant():
    assert vc.HIST_BARS_TTL_SECONDS == 30 * 60


def test_tail_length_constant():
    assert vc.TAIL_BARS_LENGTH == 200


def test_default_url_is_localhost():
    assert vc.DEFAULT_VALKEY_URL == "redis://localhost:6379/0"


def test_set_with_hist_ttl_round_trips(_swap_in_fakeredis):
    client = _swap_in_fakeredis
    key = vc.hist_key("AAPL", "1m", 100, 200)
    client.set(key, "payload", ex=vc.HIST_BARS_TTL_SECONDS)
    assert client.get(key) == "payload"
    ttl = client.ttl(key)
    assert 0 < ttl <= vc.HIST_BARS_TTL_SECONDS


def test_healthcheck_returns_true_on_live_client(_swap_in_fakeredis):
    assert vc.healthcheck() is True


def test_healthcheck_returns_false_when_no_client(monkeypatch):
    vc.reset_client_for_tests(None)
    monkeypatch.setattr(vc, "REDIS_AVAILABLE", False)
    assert vc.healthcheck() is False


def test_get_url_respects_env_override(monkeypatch):
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:7777/2")
    assert vc.get_url() == "redis://localhost:7777/2"
