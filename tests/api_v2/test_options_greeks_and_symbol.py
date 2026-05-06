"""GET /api/v2/options/greeks + /api/v2/options/symbol."""
from __future__ import annotations

from decimal import Decimal

import pytest


def _install_fake_auth(monkeypatch, broker="alpaca"):
    monkeypatch.setattr(
        "restx_api.v2.options.resolve_auth",
        lambda: ("fake-token", broker, None),
    )


def _stub_us_caps(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["us"]),
    )


# ---------------------------------------------------------------- greeks


def test_greeks_us_call_returns_full_set(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/greeks",
        query_string={
            "apikey": "x",
            "underlying": "AAPL",
            "expiry": "2026-05-15",
            "strike": "185",
            "right": "CALL",
            "spot": "190",
            "iv": "0.30",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["underlying"] == "AAPL"
    assert body["right"] == "CALL"
    assert body["region_code"] == "us"
    assert body["strike"] == "185"
    # Greeks must be parseable decimals
    for g in ("delta", "gamma", "theta", "vega"):
        Decimal(body[g])
    # ATM-ish call delta should be ~0.5..0.7
    assert 0.3 < float(body["delta"]) < 0.9


def test_greeks_us_put_delta_negative(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/greeks",
        query_string={
            "apikey": "x",
            "underlying": "AAPL",
            "expiry": "2026-05-15",
            "strike": "185",
            "right": "PUT",
            "spot": "190",
            "iv": "0.30",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    # Put delta is negative
    assert float(body["delta"]) < 0


def test_greeks_missing_param_returns_400(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/greeks",
        query_string={"apikey": "x", "underlying": "AAPL"},  # no expiry etc.
    )
    assert resp.status_code == 400


def test_greeks_bad_right_returns_400(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/greeks",
        query_string={
            "apikey": "x",
            "underlying": "AAPL",
            "expiry": "2026-05-15",
            "strike": "185",
            "right": "STRADDLE",  # invalid
            "spot": "190",
            "iv": "0.30",
        },
    )
    assert resp.status_code == 400


def test_greeks_unauthorized_returns_401(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.options.resolve_auth",
        lambda: (None, None, "missing apikey"),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/greeks",
        query_string={
            "underlying": "AAPL", "expiry": "2026-05-15",
            "strike": "185", "right": "CALL", "spot": "190", "iv": "0.30",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------- symbol


def test_symbol_format_us_round_trip(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    # Format AAPL 2024-04-19 CALL @ 185
    resp = flask_app.test_client().get(
        "/api/v2/options/symbol",
        query_string={
            "apikey": "x", "mode": "format",
            "underlying": "AAPL", "expiry": "2024-04-19",
            "strike": "185", "right": "CALL",
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["mode"] == "format"
    # OSI format: AAPL  240419C00185000
    assert body["symbol"].startswith("AAPL")
    assert "240419" in body["symbol"]
    assert "C" in body["symbol"]
    formatted = body["symbol"]

    # Round-trip: parse what we just formatted
    resp2 = flask_app.test_client().get(
        "/api/v2/options/symbol",
        query_string={"apikey": "x", "mode": "parse", "symbol": formatted},
    )
    assert resp2.status_code == 200, resp2.get_json()
    parsed = resp2.get_json()["data"]
    assert parsed["mode"] == "parse"
    assert parsed["underlying"] == "AAPL"
    assert parsed["expiry"] == "2024-04-19"
    assert parsed["right"] == "CALL"
    assert Decimal(parsed["strike"]) == Decimal("185")


def test_symbol_bad_mode_returns_400(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/symbol", query_string={"apikey": "x", "mode": "wat"},
    )
    assert resp.status_code == 400


def test_symbol_parse_invalid_returns_400(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    _stub_us_caps(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/symbol",
        query_string={"apikey": "x", "mode": "parse",
                       "symbol": "not-a-valid-osi"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "parse_error"
