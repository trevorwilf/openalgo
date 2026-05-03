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


# ---------------------------------------------------------------------------
# authenticate_broker — framework hook used by blueprints/brlogin.py
# ---------------------------------------------------------------------------


def test_authenticate_broker_returns_error_when_no_credentials():
    from broker.alpaca.api.auth_api import authenticate_broker

    auth_token, err = authenticate_broker()
    assert auth_token is None
    assert err is not None
    assert "credentials missing" in err.lower()


def test_authenticate_broker_happy_path(monkeypatch):
    """With valid keys + a 200 from /v2/account, returns a JSON token."""
    import json as _json

    import httpx

    from broker.alpaca.api import auth_api

    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")

    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "id": "fake-acct-id",
                "account_number": "PA12345",
                "currency": "USD",
                "status": "ACTIVE",
                "trading_blocked": False,
                "transfers_blocked": False,
                "account_blocked": False,
            },
            request=httpx.Request("GET", "https://paper-api.alpaca.markets/v2/account"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)

    auth_token, err = auth_api.authenticate_broker()
    assert err is None
    payload = _json.loads(auth_token)
    assert payload["api_key"] == "ak-1"
    assert payload["is_paper"] is True
    assert payload["account_id"] == "fake-acct-id"
    assert payload["account_number"] == "PA12345"


def test_authenticate_broker_rejects_blocked_account(monkeypatch):
    import httpx

    from broker.alpaca.api import auth_api

    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")

    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "id": "x",
                "currency": "USD",
                "account_blocked": True,
            },
            request=httpx.Request("GET", "https://paper-api.alpaca.markets/v2/account"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)
    auth_token, err = auth_api.authenticate_broker()
    assert auth_token is None
    assert "blocked" in err.lower()


def test_authenticate_broker_handles_401(monkeypatch):
    import httpx

    from broker.alpaca.api import auth_api

    monkeypatch.setenv("ALPACA_API_KEY", "ak-bad")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-bad")

    def _fake_get(self, url, *args, **kwargs):
        return httpx.Response(
            401,
            json={"message": "unauthorized"},
            request=httpx.Request("GET", "https://paper-api.alpaca.markets/v2/account"),
        )

    monkeypatch.setattr(httpx.Client, "get", _fake_get)
    auth_token, err = auth_api.authenticate_broker()
    assert auth_token is None
    assert "401" in err


def test_auth_handle_from_token_round_trip(monkeypatch):
    """The token emitted by authenticate_broker round-trips into an
    :class:`AlpacaAuth` carrying the same key + base URL.
    """
    import json as _json

    import httpx

    from broker.alpaca.api import auth_api
    from broker.alpaca.api.auth_api import auth_handle_from_token

    monkeypatch.setenv("ALPACA_API_KEY", "ak-1")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-1")
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, *a, **kw: httpx.Response(
            200,
            json={"id": "x", "currency": "USD"},
            request=httpx.Request("GET", "https://paper-api.alpaca.markets/v2/account"),
        ),
    )

    auth_token, err = auth_api.authenticate_broker()
    assert err is None
    handle = auth_handle_from_token(auth_token)
    assert handle.base_url == "https://paper-api.alpaca.markets"
    assert handle.headers["APCA-API-KEY-ID"] == "ak-1"
    assert handle.headers["APCA-API-SECRET-KEY"] == "sk-1"
    assert handle.is_paper is True
