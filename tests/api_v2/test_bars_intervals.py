"""GET /api/v2/bars/intervals — broker timeframe list."""
from __future__ import annotations

import pytest


def _install_fake_auth(monkeypatch, *, broker="alpaca"):
    monkeypatch.setattr(
        "restx_api.v2.bars_intervals.resolve_auth",
        lambda: ("fake-token", broker, None),
    )


def test_intervals_returns_canonical_shape(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    # Stub the legacy service so the test doesn't need a broker module.
    monkeypatch.setattr(
        "services.intervals_service.get_intervals_with_auth",
        lambda **kw: (True, {
            "status": "success",
            "data": {
                "minutes": ["1m", "5m", "15m"],
                "hours": ["1h"],
                "days": ["D"],
            },
        }, 200),
    )
    resp = flask_app.test_client().get(
        "/api/v2/bars/intervals", query_string={"apikey": "x"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["broker_code"] == "alpaca"
    assert "1m" in body["intervals"]["minutes"]
    assert "D" in body["intervals"]["days"]


def test_intervals_unauthorized_returns_401(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.bars_intervals.resolve_auth",
        lambda: (None, None, "missing apikey"),
    )
    resp = flask_app.test_client().get("/api/v2/bars/intervals")
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "unauthorized"


def test_intervals_broker_error_propagates(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)
    monkeypatch.setattr(
        "services.intervals_service.get_intervals_with_auth",
        lambda **kw: (False, {"status": "error", "message": "broker not loaded"}, 502),
    )
    resp = flask_app.test_client().get(
        "/api/v2/bars/intervals", query_string={"apikey": "x"},
    )
    assert resp.status_code == 502
    body = resp.get_json()["error"]
    assert body["code"] == "broker_error"
    assert "broker not loaded" in body["message"]
