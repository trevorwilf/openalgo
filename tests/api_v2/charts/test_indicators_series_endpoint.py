"""Phase 5 — POST /api/v2/indicators/series shape contract."""

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


def _bars():
    base = 1700000040
    return [
        {
            "t": base + i * 60,
            "o": str(100 + i),
            "h": str(101 + i),
            "l": str(99 + i),
            "c": str(100 + i),
            "v": "1000",
            "oi": None,
        }
        for i in range(30)
    ]


def test_unknown_indicator_returns_404(client, stub_auth):
    resp = client.post(
        "/api/v2/indicators/series",
        json={"apikey": "k", "indicator_key": "FAKE", "bars": _bars()},
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "unknown_indicator"


def test_missing_bars_returns_400(client, stub_auth):
    resp = client.post(
        "/api/v2/indicators/series",
        json={"apikey": "k", "indicator_key": "SMA"},
    )
    assert resp.status_code == 400


def test_sma_returns_series(client, stub_auth):
    resp = client.post(
        "/api/v2/indicators/series",
        json={"apikey": "k", "indicator_key": "SMA", "bars": _bars(), "params": {"period": 5}},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["indicator_key"] == "SMA"
    assert isinstance(data["series"], list)
    assert len(data["series"]) == 30
    # First few are warmup nulls; later ones are numbers.
    last = data["series"][-1]["values"]["sma"]
    assert last is not None
