"""Phase 6 — analyzer route is gated to India region.

The existing capability gate (``@requires_capability("supports_analyzer")``)
allowed the Alpaca plugin (which sets ``supports_analyzer: true``) to
hit the analyzer routes. Phase 6 adds an explicit India-only gate
that fails closed regardless of broker capabilities.
"""

from __future__ import annotations

import pytest
from flask import Flask, jsonify


@pytest.fixture
def gated_app(monkeypatch):
    from utils.capability_guards import india_region_only

    app = Flask(__name__)
    app.secret_key = "phase6-test"

    @app.route("/analyzer-test")
    @india_region_only()
    def _view():
        return jsonify({"status": "ok"})

    return app


def test_india_region_passes_through(monkeypatch, gated_app):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "india")
    resp = gated_app.test_client().get("/analyzer-test")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_us_region_returns_404_with_stable_code(monkeypatch, gated_app):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "us")
    resp = gated_app.test_client().get("/analyzer-test")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["code"] == "analyzer_india_region_only"
    assert "us" in body["message"]


def test_eu_region_returns_404(monkeypatch, gated_app):
    monkeypatch.setenv("MARKET_REGION_FOR_TESTS", "eu")
    resp = gated_app.test_client().get("/analyzer-test")
    assert resp.status_code == 404
