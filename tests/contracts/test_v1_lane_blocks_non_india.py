"""Phase 2 v4 (ADR 0023, invariant 5) — v1 hard-block for non-India brokers,
with v1→v2 compatibility bridge.

The legacy ``/api/v1/*`` routes carry implicit India semantics. The
ADR's intent is "non-India brokers must never invoke the legacy India
services". The implementation honors that intent in two stages:

  1. **Bridged.** ``services/v1_compat_bridge.py::BRIDGES`` registers
     handlers for every v1 path that has a clean ``/api/v2``
     equivalent. The bridge re-shapes the request and dispatches
     internally through ``/api/v2`` so the legacy India services are
     never invoked. Bridged paths return whatever shape the handler
     produces (typically the v1 envelope, populated from v2 data).
  2. **410 Gone.** When the path has no bridge handler, the guard
     returns HTTP 410 Gone with structured payload
     ``{"status":"error","code":"v1_unavailable_for_non_india_broker"}``.

This test exercises the request-time guard installed in
``restx_api/__init__.py:_v1_block_non_india_brokers_or_sunset`` against
representative routes. India brokers continue to receive their normal
response. The bridge tests stub ``services.v1_compat_bridge.try_bridge``
so the underlying broker translator stays out of the test.
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


def _stub_bridge_miss(monkeypatch):
    """Pretend no v1→v2 bridge handler matches the path so the guard
    falls through to its 410 path. Useful for testing the
    no-bridge-coverage branch.
    """
    monkeypatch.setattr(
        "services.v1_compat_bridge.try_bridge",
        lambda broker, path: None,
    )


def _stub_bridge_hit(monkeypatch, payload, status):
    """Pretend a v1→v2 bridge handler matches and returns ``(payload,
    status)``. Useful for testing the bridge-passthrough branch
    without dragging the real broker translator into the test.
    """
    from flask import jsonify

    def fake_try_bridge(broker, path):
        return jsonify(payload), status

    monkeypatch.setattr(
        "services.v1_compat_bridge.try_bridge", fake_try_bridge
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


def test_non_india_broker_bridged_when_handler_matches(flask_app, monkeypatch):
    """Updated v6+ contract: non-India broker hitting a bridged v1 path
    runs through the v1→v2 compatibility bridge and gets a real
    response, not a 410. The legacy India services are still never
    invoked (the bridge dispatches internally through /api/v2).

    Pre-fix this test asserted 410; the actual production behavior
    has been "bridge passthrough" since the v1_compat_bridge shipped.
    """
    _stub_caps(monkeypatch, ["us"])
    _stub_bridge_hit(
        monkeypatch,
        {"status": "success", "data": {"orders": [], "statistics": {}}},
        200,
    )
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "success"


def test_non_india_broker_blocked_with_410_when_bridge_misses(
    flask_app, monkeypatch
):
    """The 410 branch still fires for paths the bridge does not cover.
    Stubbing ``try_bridge`` to return None forces this branch even on
    a path that today *is* bridged, so the test stays true even as the
    bridge coverage grows.
    """
    _stub_caps(monkeypatch, ["us"])
    _stub_bridge_miss(monkeypatch)
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/orderbook/", json={"apikey": "k"})
    assert resp.status_code == 410, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["code"] == "v1_unavailable_for_non_india_broker"
    assert body["details"]["broker_code"] == "alpaca"
    assert body["details"]["promoted_lane_root"] == "/api/v2"


def test_non_india_broker_quotes_bridged(flask_app, monkeypatch):
    """``/api/v1/quotes`` is one of the bridged paths today. Passthrough
    semantics: the bridge handler runs and the test sees its
    response, not a 410."""
    _stub_caps(monkeypatch, ["us"])
    _stub_bridge_hit(
        monkeypatch,
        {"status": "success", "data": {"bid": "1", "ask": "1"}},
        200,
    )
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/quotes/", json={"apikey": "k", "symbol": "AAPL"})
    assert resp.status_code == 200


def test_non_india_broker_funds_bridged(flask_app, monkeypatch):
    """``/api/v1/funds`` is bridged for Alpaca. Same passthrough
    contract as quotes/orderbook."""
    _stub_caps(monkeypatch, ["us"])
    _stub_bridge_hit(
        monkeypatch,
        {"status": "success", "data": {"availablecash": "100000"}},
        200,
    )
    client = flask_app.test_client()
    _set_session_broker(client, "alpaca")
    resp = client.post("/api/v1/funds/", json={"apikey": "k"})
    assert resp.status_code == 200


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
