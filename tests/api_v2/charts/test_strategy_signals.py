"""Phase 6 — strategy signals endpoint contract."""

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


def test_signals_get_unauthenticated_401(client):
    resp = client.get("/api/v2/strategy-signals")
    assert resp.status_code == 401


def test_signals_post_requires_symbol_kind_source(client, stub_auth):
    resp = client.post(
        "/api/v2/strategy-signals",
        json={"apikey": "k"},
    )
    assert resp.status_code == 400


def test_signals_round_trip(client, stub_auth):
    resp = client.post(
        "/api/v2/strategy-signals",
        json={
            "apikey": "k",
            "symbol": "AAPL",
            "kind": "BUY",
            "source": "test-strategy",
            "payload_json": {"price": 100.5},
        },
    )
    assert resp.status_code == 201
    created = resp.get_json()["data"]
    assert created["symbol"] == "AAPL"
    assert created["kind"] == "BUY"
    if created["id"] > 0:
        resp = client.get("/api/v2/strategy-signals?apikey=k&symbol=AAPL")
        rows = resp.get_json()["data"]
        kinds = [r["kind"] for r in rows]
        assert "BUY" in kinds
