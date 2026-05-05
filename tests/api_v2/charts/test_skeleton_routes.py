"""Phase 1 — /api/v2/chart/* skeleton routes return shape-correct stubs.

Each route is exercised with a stubbed auth boundary so we don't need
a real API key in the test DB. The test asserts:

* Auth missing / invalid → 401 with ``error.code == 'unauthorized'``.
* GET endpoints → 200 with ``data`` envelope.
* POST endpoints → 201 with the persisted (or stub) row's keys.
* PUT endpoints → 200 with ``data`` envelope.
* DELETE endpoints → 204 (no body).
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def stub_auth(monkeypatch):
    """Stub ``database.auth_db.get_auth_token_broker`` so the v2 chart
    common helper accepts any non-empty apikey as authenticated.
    """
    def fake(api_key, include_feed_token=False):
        if not api_key:
            return None, None, None
        if include_feed_token:
            return "tok", None, "alpaca"
        return "tok", "alpaca"

    monkeypatch.setattr(
        "restx_api.v2.chart._common.get_auth_token_broker",
        fake,
    )
    monkeypatch.setattr(
        "restx_api.v2._auth.get_auth_token_broker",
        fake,
    )


def _api_key_body(extra: dict | None = None) -> dict:
    body = {"apikey": "test-key-123"}
    if extra:
        body.update(extra)
    return body


def test_layouts_get_returns_empty_data_envelope(client, stub_auth):
    resp = client.get("/api/v2/chart/layouts?apikey=test-key-123")
    assert resp.status_code == 200
    assert resp.get_json() == {"data": []}


def test_layouts_get_unauthenticated_returns_401(client):
    resp = client.get("/api/v2/chart/layouts")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"]["code"] == "unauthorized"


def test_layouts_post_returns_201_with_layout_shape(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/layouts",
        json=_api_key_body({"name": "Default", "schema_version": 1, "cells_json": {}}),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    for k in ("id", "user_id", "name", "schema_version", "cells_json", "created_at"):
        assert k in data
    assert data["name"] == "Default"
    assert data["schema_version"] == 1


def test_layout_get_put_delete(client, stub_auth):
    # Phase 5 wires real DB-backed CRUD. Create first so the GET/PUT/DELETE
    # operate on a real row.
    resp = client.post(
        "/api/v2/chart/layouts",
        json=_api_key_body({"name": "Test", "schema_version": 1, "cells_json": {}}),
    )
    assert resp.status_code == 201
    layout_id = resp.get_json()["data"]["id"]

    resp = client.get(f"/api/v2/chart/layouts/{layout_id}?apikey=test-key-123")
    assert resp.status_code == 200
    resp = client.put(
        f"/api/v2/chart/layouts/{layout_id}",
        json=_api_key_body({"name": "x"}),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == layout_id
    resp = client.delete(f"/api/v2/chart/layouts/{layout_id}?apikey=test-key-123")
    assert resp.status_code == 204


def test_layout_cells_get_and_put(client, stub_auth):
    # Phase 5: GET/PUT for /<id>/cells operates on a real layout row.
    resp = client.post(
        "/api/v2/chart/layouts",
        json=_api_key_body({"name": "Cells Test", "schema_version": 1, "cells_json": {"cells": []}}),
    )
    assert resp.status_code == 201
    layout_id = resp.get_json()["data"]["id"]

    resp = client.get(f"/api/v2/chart/layouts/{layout_id}/cells?apikey=test-key-123")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["layout_id"] == layout_id
    assert body["cells"] == []
    resp = client.put(
        f"/api/v2/chart/layouts/{layout_id}/cells",
        json=_api_key_body({"cells": []}),
    )
    assert resp.status_code == 200


def test_drawings_full_crud(client, stub_auth):
    resp = client.get("/api/v2/chart/drawings?apikey=test-key-123")
    assert resp.status_code == 200
    resp = client.post(
        "/api/v2/chart/drawings",
        json=_api_key_body({"layout_id": 1, "cell_id": "c1", "kind": "trendline"}),
    )
    assert resp.status_code == 201
    drawing_id = resp.get_json()["data"]["id"]
    assert resp.get_json()["data"]["kind"] == "trendline"
    resp = client.put(
        f"/api/v2/chart/drawings/{drawing_id}", json=_api_key_body({"kind": "trendline"})
    )
    assert resp.status_code == 200
    resp = client.delete(f"/api/v2/chart/drawings/{drawing_id}?apikey=test-key-123")
    assert resp.status_code == 204


def test_indicators_full_crud(client, stub_auth):
    resp = client.get("/api/v2/chart/indicators?apikey=test-key-123")
    assert resp.status_code == 200
    resp = client.post(
        "/api/v2/chart/indicators",
        json=_api_key_body({
            "layout_id": 1,
            "cell_id": "c1",
            "indicator_key": "RSI",
            "params_json": {"period": 14},
        }),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    indicator_id = data["id"]
    assert data["indicator_key"] == "RSI"
    assert data["params_json"] == {"period": 14}
    assert client.put(
        f"/api/v2/chart/indicators/{indicator_id}", json=_api_key_body({})
    ).status_code == 200
    assert (
        client.delete(f"/api/v2/chart/indicators/{indicator_id}?apikey=test-key-123").status_code
        == 204
    )


def test_watchlists_get_handles_missing_db_gracefully(client, stub_auth):
    resp = client.get("/api/v2/chart/watchlists?apikey=test-key-123")
    # Either successful empty list, or the DB-backed implementation
    # returning a list (when the table exists in the test env).
    assert resp.status_code == 200
    body = resp.get_json()
    assert "data" in body
    assert isinstance(body["data"], list)


def test_watchlists_post_returns_201(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/watchlists",
        json=_api_key_body({"name": "Tech Stocks", "symbols": ["AAPL", "MSFT"]}),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Tech Stocks"
    assert data["symbols"] == ["AAPL", "MSFT"]


def test_watchlists_post_rejects_missing_name(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/watchlists",
        json=_api_key_body({"symbols": []}),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_templates_full_crud(client, stub_auth):
    resp = client.get("/api/v2/chart/templates?apikey=test-key-123")
    assert resp.status_code == 200
    resp = client.post(
        "/api/v2/chart/templates",
        json=_api_key_body({"name": "4-quad scalp", "schema_version": 1, "cells_json": {}}),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "4-quad scalp"
    assert (
        client.put("/api/v2/chart/templates/1", json=_api_key_body({})).status_code
        == 200
    )
    assert (
        client.delete("/api/v2/chart/templates/1?apikey=test-key-123").status_code
        == 204
    )


def test_active_layout_get_and_put(client, stub_auth):
    resp = client.get("/api/v2/chart/active-layout?apikey=test-key-123")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert "layout_id" in body
    resp = client.put(
        "/api/v2/chart/active-layout",
        json=_api_key_body({"layout_id": 11}),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["layout_id"] == 11
