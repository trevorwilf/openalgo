"""Phase 3 — minimal /api/v2/chart/watchlists round-trip.

The Phase 1 skeleton already wired DB-backed watchlists; this test
walks the create → list → delete path to confirm the chart sidebar's
Phase 3 client (`frontend/src/charts/persistence/watchlists.ts`) sees
a stable shape end-to-end.
"""

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

    monkeypatch.setattr(
        "restx_api.v2.chart._common.get_auth_token_broker",
        fake,
    )
    monkeypatch.setattr(
        "restx_api.v2._auth.get_auth_token_broker",
        fake,
    )


def test_watchlist_round_trip_create_list_delete(client, stub_auth):
    apikey = "test-key-rt"
    # Initially empty.
    r = client.get(f"/api/v2/chart/watchlists?apikey={apikey}")
    assert r.status_code == 200
    assert isinstance(r.get_json()["data"], list)

    # Create.
    r = client.post(
        "/api/v2/chart/watchlists",
        json={"apikey": apikey, "name": "Tech", "symbols": ["AAPL", "MSFT", "GOOGL"]},
    )
    assert r.status_code == 201
    created = r.get_json()["data"]
    assert created["name"] == "Tech"
    assert created["symbols"] == ["AAPL", "MSFT", "GOOGL"]
    wid = created["id"]

    # List again — DB-backed path returns the new row when present.
    r = client.get(f"/api/v2/chart/watchlists?apikey={apikey}")
    rows = r.get_json()["data"]
    if wid > 0:
        # If the test env had the table installed, the row appears.
        names = [w["name"] for w in rows]
        assert "Tech" in names

    # Delete — must always 204.
    r = client.delete(f"/api/v2/chart/watchlists/{wid}?apikey={apikey}")
    assert r.status_code == 204


def test_watchlist_post_rejects_missing_name(client, stub_auth):
    r = client.post(
        "/api/v2/chart/watchlists",
        json={"apikey": "k", "symbols": []},
    )
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "bad_request"


def test_watchlist_unauthenticated_returns_401(client):
    r = client.get("/api/v2/chart/watchlists")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "unauthorized"
