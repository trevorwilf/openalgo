"""Tests for GET /api/v2/ping liveness probe."""
from __future__ import annotations


def test_ping_returns_200_with_ok_payload(flask_app):
    resp = flask_app.test_client().get("/api/v2/ping")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert body["version"] == "2.0"


def test_ping_no_auth_required(flask_app):
    """ping is a liveness probe — no API key, no session, must work."""
    resp = flask_app.test_client().get("/api/v2/ping")
    assert resp.status_code == 200


def test_ping_trailing_slash(flask_app):
    """Both /ping and /ping/ resolve."""
    r1 = flask_app.test_client().get("/api/v2/ping")
    r2 = flask_app.test_client().get("/api/v2/ping/")
    assert r1.status_code == 200
    assert r2.status_code == 200
