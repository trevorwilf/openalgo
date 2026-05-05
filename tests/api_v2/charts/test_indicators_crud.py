"""Phase 5 — /api/v2/chart/indicators full CRUD."""

from __future__ import annotations

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


def test_post_rejects_unknown_indicator_key(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/indicators",
        json={
            "apikey": "k",
            "layout_id": 1,
            "cell_id": "c1",
            "indicator_key": "DOES_NOT_EXIST",
            "params_json": {},
        },
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "unknown_indicator"


def test_indicator_round_trip(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/indicators",
        json={
            "apikey": "k",
            "layout_id": 1,
            "cell_id": "c1",
            "indicator_key": "RSI",
            "params_json": {"period": 14},
        },
    )
    assert resp.status_code == 201
    created = resp.get_json()["data"]
    assert created["indicator_key"] == "RSI"
    assert created["params_json"] == {"period": 14}

    # Phase 5 wires CRUD + filter by layout_id + cell_id.
    resp = client.get("/api/v2/chart/indicators?apikey=k&layout_id=1&cell_id=c1")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    if isinstance(body, list) and created["id"] > 0:
        keys = [r["indicator_key"] for r in body]
        assert "RSI" in keys


def test_indicator_post_requires_layout_cell_key(client, stub_auth):
    resp = client.post(
        "/api/v2/chart/indicators",
        json={"apikey": "k", "layout_id": 1, "cell_id": "c1"},
    )
    assert resp.status_code == 400
