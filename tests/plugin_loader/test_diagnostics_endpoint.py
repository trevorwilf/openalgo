"""Phase 4 v4 (ADR 0025) — /api/v2/plugins/diagnostics endpoint.

Confirms the endpoint shape: a top-level summary dict + a per-broker
``brokers`` map keyed by broker_code with state / promoted /
broker_type / supported_regions fields.
"""

from __future__ import annotations

import pytest

from utils import plugin_loader


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setenv("API_V2", "1")
    from flask import Flask

    from restx_api.v2 import register_api_v2

    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_api_v2(app)
    return app


def test_diagnostics_endpoint_returns_summary(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.plugins.get_plugin_diagnostics",
        lambda: {
            "alpaca": {
                "state": "loaded",
                "promoted": True,
                "broker_type": "US_stock",
                "supported_regions": ["us"],
            },
            "_mock_schwab_like": {
                "state": "loaded",
                "promoted": True,
                "broker_type": "US_stock",
                "supported_regions": ["us"],
            },
            "zerodha": {
                "state": "loaded",
                "promoted": False,
                "broker_type": "IN_stock",
                "supported_regions": [],
            },
            "broken_broker": {
                "state": "skipped",
                "promoted": True,
                "reason": "strict_mode_failed",
                "errors": ["unknown promoted plugin field 'foo'"],
            },
        },
    )
    client = flask_app.test_client()
    resp = client.get("/api/v2/plugins/diagnostics")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    data = body["data"]
    summary = data["summary"]
    assert summary["loaded"] == 3
    assert summary["skipped"] == 1
    assert summary["promoted_loaded"] == 2
    brokers = data["brokers"]
    assert "alpaca" in brokers
    assert brokers["broken_broker"]["reason"] == "strict_mode_failed"
    assert brokers["broken_broker"]["errors"] == [
        "unknown promoted plugin field 'foo'"
    ]


def test_diagnostics_endpoint_works_with_empty_state(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.plugins.get_plugin_diagnostics", lambda: {}
    )
    client = flask_app.test_client()
    resp = client.get("/api/v2/plugins/diagnostics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["summary"]["loaded"] == 0
    assert body["data"]["brokers"] == {}
