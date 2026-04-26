"""Phase 2 v4 (ADR 0023, invariant 5) — v1 hard-block for non-India brokers.

The legacy ``/api/v1/*`` routes carry implicit India semantics. A
non-India broker session reaching any v1 route must receive a
structured 410 Gone response with code
``v1_unavailable_for_non_india_broker``.

This test exercises the request-time guard installed in
``restx_api/__init__.py:_v1_block_non_india_brokers`` against
representative routes (orders, quotes, history, funds, orderbook).
India brokers continue to receive their normal response (or normal
auth failure).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def flask_app(monkeypatch):
    """Build a minimal Flask app with the v1 blueprint mounted.

    No sys.modules surgery — we just import restx_api and reuse the
    already-loaded module. Re-importing causes state leak in other
    tests (the v2 sub-package keeps its own reference cycle).
    """
    import importlib

    restx_api = importlib.import_module("restx_api")

    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(restx_api.api_v1_bp)
    return app


def _set_session_broker(client, broker):
    with client.session_transaction() as sess:
        sess["broker"] = broker


def _stub_caps(monkeypatch, regions):
    caps = SimpleNamespace(supported_regions=regions)
    # Patch the source module — the v1 guard does a function-local
    # ``from utils.plugin_loader import get_broker_capabilities`` so
    # patching there is the cleanest.
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda broker: caps,
    )


def test_no_session_broker_passes_guard(flask_app, monkeypatch):
    """First request before login: guard returns None; downstream auth
    handles the 401 / API key validation."""
    client = flask_app.test_client()
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    # The guard returned None; the schema/auth layer rejects with
    # something other than 410.
    assert resp.status_code != 410


def test_india_broker_passes_guard(flask_app, monkeypatch):
    _stub_caps(monkeypatch, ["india"])
    client = flask_app.test_client()
    _set_session_broker(client, "zerodha")
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    assert resp.status_code != 410


def test_non_india_broker_blocked_with_410(flask_app, monkeypatch):
    _stub_caps(monkeypatch, ["us"])
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    assert resp.status_code == 410, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["code"] == "v1_unavailable_for_non_india_broker"
    assert body["details"]["broker_code"] == "alpaca"
    assert body["details"]["promoted_lane_root"] == "/api/v2"


def test_non_india_broker_blocked_for_quotes(flask_app, monkeypatch):
    _stub_caps(monkeypatch, ["us"])
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/quotes/", json={"apikey": "k", "symbol": "AAPL"})
    assert resp.status_code == 410


def test_non_india_broker_blocked_for_funds(flask_app, monkeypatch):
    _stub_caps(monkeypatch, ["us"])
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/funds/", json={"apikey": "k"})
    assert resp.status_code == 410


def test_unknown_broker_capabilities_passes_guard(flask_app, monkeypatch):
    """A broker plugin without explicit supported_regions (legacy India
    plugin shape) is allowed through — bit-identical India behavior."""
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda broker: None,
    )
    client = flask_app.test_client()
    _set_session_broker(client, "some-legacy-india-broker")
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    assert resp.status_code != 410
