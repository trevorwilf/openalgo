"""Alpaca auth — credential loading and AlpacaAuth handle shape."""

from __future__ import annotations

import pytest

from broker.alpaca.api.auth_api import (
    LIVE_BASE_URL,
    PAPER_BASE_URL,
    authenticate,
    load_credentials,
)


def test_load_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
    k, s, is_paper = load_credentials()
    assert k == "ak-1"
    assert s == "sk-1"
    assert is_paper is True  # default = paper


def test_load_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(ValueError):
        load_credentials()


def test_authenticate_paper_defaults(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
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
