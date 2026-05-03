"""Contract tests for ``services.broker_mode_resolver``.

The resolver feeds the React header's PAPER / LIVE badge — getting
this wrong means an operator can't tell which environment they're
about to send a real order to. The mapping is therefore worth
locking with explicit cases so any future broker-config change
surfaces here first.
"""

from __future__ import annotations

import pytest

from services.broker_mode_resolver import resolve_broker_mode


_AUTH_ENV = (
    "ALPACA_LIVE_MODE",
    "ALPACA_PAPER",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "BROKER_API_KEY",
    "BROKER_API_SECRET",
    "BROKER_API_KEY_MARKET",
    "BROKER_API_SECRET_MARKET",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _AUTH_ENV:
        monkeypatch.delenv(var, raising=False)


def test_alpaca_paper_key_resolves_paper(monkeypatch):
    """PK-prefixed key + no env override → paper."""
    monkeypatch.setenv("BROKER_API_KEY", "PKH45M3VMLQJYIANBL47MKY3AZ")
    assert resolve_broker_mode("alpaca") == "paper"


def test_alpaca_live_key_with_live_mode_resolves_live(monkeypatch):
    """AK-prefixed key + ALPACA_LIVE_MODE=1 → live."""
    monkeypatch.setenv("ALPACA_LIVE_MODE", "1")
    monkeypatch.setenv("BROKER_API_KEY_MARKET", "AK32TFOCXNHCMIJUCVIXXZLWDO")
    assert resolve_broker_mode("alpaca") == "live"


def test_alpaca_live_key_without_live_mode_resolves_unknown(monkeypatch):
    """AK key in BROKER_API_KEY (paper slot) without ALPACA_LIVE_MODE
    is a misconfiguration — flag it instead of guessing."""
    monkeypatch.setenv("BROKER_API_KEY", "AKsomelivekey1234567")
    assert resolve_broker_mode("alpaca") == "unknown"


def test_alpaca_explicit_key_overrides_broker_pair(monkeypatch):
    """ALPACA_API_KEY beats BROKER_API_KEY when both are set —
    matches the auth resolver's precedence."""
    monkeypatch.setenv("ALPACA_API_KEY", "PKexplicitpaperkey")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.setenv("BROKER_API_KEY_MARKET", "AKlivekeymeantforproduction")
    assert resolve_broker_mode("alpaca") == "paper"


def test_alpaca_no_keys_resolves_unknown():
    """No keys set → can't say."""
    assert resolve_broker_mode("alpaca") == "unknown"


def test_alpaca_paper_env_zero_means_live(monkeypatch):
    """ALPACA_PAPER=0 is the legacy "go live" toggle. With an AK key
    in the live slot, that resolves to live."""
    monkeypatch.setenv("ALPACA_PAPER", "0")
    monkeypatch.setenv("BROKER_API_KEY_MARKET", "AK32TFOCXNHCMIJUCVIXXZLWDO")
    assert resolve_broker_mode("alpaca") == "live"


def test_indian_brokers_resolve_live():
    """Indian brokers don't have a parallel paper API — the broker
    session is always real (the user's analyzer toggle is what
    makes trading simulated)."""
    for broker in ("zerodha", "angel", "upstox", "fyers", "dhan"):
        assert resolve_broker_mode(broker) == "live", broker


def test_unknown_broker_resolves_unknown():
    """Unrecognised broker name → unknown until a per-broker rule
    is added."""
    assert resolve_broker_mode("nonexistent_broker") == "unknown"


def test_none_broker_resolves_unknown():
    assert resolve_broker_mode(None) == "unknown"
    assert resolve_broker_mode("") == "unknown"


def test_placeholder_keys_treated_as_missing(monkeypatch):
    """The .sample.env placeholders shouldn't accidentally resolve
    to a mode — operators that haven't filled in real keys yet
    should see ``unknown``."""
    monkeypatch.setenv("BROKER_API_KEY", "YOUR_BROKER_API_KEY")
    assert resolve_broker_mode("alpaca") == "unknown"
