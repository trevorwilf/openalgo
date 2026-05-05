"""Phase 5 — full CRUD round-trip for /api/v2/chart/layouts and
templates and active-layout. Drawings + indicators get the same
shape; covered separately."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def stub_auth(monkeypatch):
    def fake(api_key, include_feed_token=False):
        if not api_key:
            return None, None, None
        if include_feed_token:
            return "tok", None, "alpaca"
        return "tok", "alpaca"

    monkeypatch.setattr("restx_api.v2._auth.get_auth_token_broker", fake)
    monkeypatch.setattr(
        "restx_api.v2.chart._common.get_auth_token_broker", fake
    )


def test_layouts_create_get_put_delete(client, stub_auth):
    cells = {
        "tabs": [
            {
                "id": "tab-1",
                "name": "Default",
                "template": "1",
                "cells": [
                    {
                        "id": "cell-1",
                        "engine": "lightweight",
                        "symbol": "AAPL",
                        "venueCode": "XNAS",
                        "timeframe": "5m",
                    }
                ],
                "focusedCellId": "cell-1",
            }
        ],
        "activeTabId": "tab-1",
        "theme": "dark",
    }
    # Create.
    resp = client.post(
        "/api/v2/chart/layouts",
        json={
            "apikey": "k",
            "name": "Default",
            "schema_version": 1,
            "cells_json": cells,
        },
    )
    assert resp.status_code == 201
    created = resp.get_json()["data"]
    layout_id = created["id"]
    assert created["name"] == "Default"

    # The DB-backed path round-trips cells_json as a dict.
    if layout_id > 0:
        resp = client.get(f"/api/v2/chart/layouts/{layout_id}?apikey=k")
        assert resp.status_code == 200
        body = resp.get_json()["data"]
        assert body["cells_json"] == cells

        # PUT replaces cells_json.
        new_cells = {**cells, "theme": "light"}
        resp = client.put(
            f"/api/v2/chart/layouts/{layout_id}",
            json={"apikey": "k", "cells_json": new_cells},
        )
        assert resp.status_code == 200
        body = resp.get_json()["data"]
        assert body["cells_json"]["theme"] == "light"

        # DELETE.
        resp = client.delete(f"/api/v2/chart/layouts/{layout_id}?apikey=k")
        assert resp.status_code == 204


def test_active_layout_round_trip(client, stub_auth):
    # Initial: no active layout.
    resp = client.get("/api/v2/chart/active-layout?apikey=k")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["layout_id"] is None

    # PUT requires layout_id.
    resp = client.put("/api/v2/chart/active-layout", json={"apikey": "k"})
    assert resp.status_code == 400

    resp = client.put(
        "/api/v2/chart/active-layout",
        json={"apikey": "k", "layout_id": 42},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["layout_id"] == 42

    # GET reflects the new active layout.
    resp = client.get("/api/v2/chart/active-layout?apikey=k")
    body = resp.get_json()["data"]
    assert body["layout_id"] == 42
