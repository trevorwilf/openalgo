"""Alpaca auth — credential loading and AlpacaAuth handle shape."""

from __future__ import annotations

import pytest

from broker.alpaca.api.auth_api import (
    LIVE_BASE_URL,
    PAPER_BASE_URL,
    authenticate,
    load_credentials,
)


# All env vars the resolver consults. Tests delete every one of them
# at setup so a leak from the parent shell / pytest .env doesn't make
# a test pass for the wrong reason.
_AUTH_ENV_VARS = (
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "ALPACA_PAPER",
    "ALPACA_LIVE_MODE",
    "BROKER_API_KEY",
    "BROKER_API_SECRET",
    "BROKER_API_KEY_MARKET",
    "BROKER_API_SECRET_MARKET",
)


@pytest.fixture(autouse=True)
def _clean_alpaca_env(monkeypatch):
    for var in _AUTH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Source 1: explicit ALPACA_API_KEY / ALPACA_API_SECRET (prior behavior).
# ---------------------------------------------------------------------------


def test_load_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    k, s, is_paper = load_credentials()
    assert k == "ak-1"
    assert s == "sk-1"
    assert is_paper is True  # default = paper


def test_load_credentials_missing_raises():
    with pytest.raises(ValueError):
        load_credentials()


def test_authenticate_paper_defaults(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    auth = authenticate()
    assert auth.base_url == PAPER_BASE_URL
    assert auth.is_paper is True
    assert auth.headers["APCA-API-KEY-ID"] == "ak-1"
    assert auth.headers["APCA-API-SECRET-KEY"] == "sk-1"


def test_authenticate_live_when_paper_zero(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak-live")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-live")
    monkeypatch.setenv("ALPACA_PAPER", "0")
    auth = authenticate()
    assert auth.base_url == LIVE_BASE_URL
    assert auth.is_paper is False


# ---------------------------------------------------------------------------
# Source 2: generic BROKER_API_* convention (Branch A — dual-source auth).
# ---------------------------------------------------------------------------


def test_paper_falls_back_to_broker_api_key(monkeypatch):
    """ALPACA_* unset → use BROKER_API_KEY/SECRET in paper mode."""
    monkeypatch.setenv("BROKER_API_KEY", "paper-ak")
    monkeypatch.setenv("BROKER_API_SECRET", "paper-sk")
    k, s, is_paper = load_credentials()
    assert k == "paper-ak"
    assert s == "paper-sk"
    assert is_paper is True


def test_live_falls_back_to_broker_api_key_market(monkeypatch):
    """ALPACA_LIVE_MODE=1 + ALPACA_* unset → use BROKER_API_KEY_MARKET pair."""
    monkeypatch.setenv("ALPACA_LIVE_MODE", "1")
    monkeypatch.setenv("BROKER_API_KEY_MARKET", "live-ak")
    monkeypatch.setenv("BROKER_API_SECRET_MARKET", "live-sk")
    k, s, is_paper = load_credentials()
    assert k == "live-ak"
    assert s == "live-sk"
    assert is_paper is False


def test_alpaca_explicit_wins_over_broker_fallback(monkeypatch):
    """When both sources are populated, ALPACA_API_KEY/SECRET takes precedence."""
    monkeypatch.setenv("ALPACA_API_KEY", "explicit-ak")
    monkeypatch.setenv("ALPACA_API_SECRET", "explicit-sk")
    monkeypatch.setenv("BROKER_API_KEY", "fallback-ak")
    monkeypatch.setenv("BROKER_API_SECRET", "fallback-sk")
    k, s, _ = load_credentials()
    assert k == "explicit-ak"
    assert s == "explicit-sk"


def test_paper_fallback_ignored_in_live_mode(monkeypatch):
    """ALPACA_LIVE_MODE=1 must NOT pick up BROKER_API_KEY (which is the paper slot).

    The error message names the live-slot vars so the operator knows
    which keys they need to set.
    """
    monkeypatch.setenv("ALPACA_LIVE_MODE", "1")
    monkeypatch.setenv("BROKER_API_KEY", "paper-ak")
    monkeypatch.setenv("BROKER_API_SECRET", "paper-sk")
    with pytest.raises(ValueError) as exc_info:
        load_credentials()
    assert "BROKER_API_KEY_MARKET" in str(exc_info.value)


def test_placeholder_values_are_treated_as_missing(monkeypatch):
    """`.sample.env` placeholders ('YOUR_BROKER_API_KEY') must not auth."""
    monkeypatch.setenv("BROKER_API_KEY", "YOUR_BROKER_API_KEY")
    monkeypatch.setenv("BROKER_API_SECRET", "YOUR_BROKER_API_SECRET")
    with pytest.raises(ValueError):
        load_credentials()


def test_alpaca_live_mode_supersedes_alpaca_paper(monkeypatch):
    """When both ALPACA_LIVE_MODE and ALPACA_PAPER are set,
    ALPACA_LIVE_MODE wins (it's the canonical Branch A flag).
    """
    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    monkeypatch.setenv("ALPACA_LIVE_MODE", "1")
    monkeypatch.setenv("ALPACA_PAPER", "1")  # would normally mean paper
    auth = authenticate()
    assert auth.base_url == LIVE_BASE_URL
    assert auth.is_paper is False
