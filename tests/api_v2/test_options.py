"""GET /api/v2/options/{expiries,chain} — region-driven dispatch."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


def _install_fake_auth_expiries(monkeypatch, broker="alpaca"):
    monkeypatch.setattr(
        "restx_api.v2.options.resolve_auth",
        lambda: ("fake-token", broker, None),
    )


def test_expiries_us_region_returns_list(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["us"]),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/expiries",
        query_string={"apikey": "x", "underlying": "AAPL",
                       "asof": "2026-05-06"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["underlying"] == "AAPL"
    assert body["region_code"] == "us"
    assert body["asof"] == "2026-05-06"
    # US provider returns 8 weekly Fridays from the as-of date.
    assert len(body["expiries"]) == 8
    # Every entry parses as ISO YYYY-MM-DD.
    for d in body["expiries"]:
        assert date.fromisoformat(d).year == 2026


def test_expiries_underlying_uppercased(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["us"]),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/expiries",
        query_string={"apikey": "x", "underlying": "aapl"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["underlying"] == "AAPL"


def test_expiries_missing_underlying_returns_400(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/expiries", query_string={"apikey": "x"},
    )
    assert resp.status_code == 400


def test_expiries_bad_asof_returns_400(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["us"]),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/expiries",
        query_string={"apikey": "x", "underlying": "AAPL", "asof": "not-a-date"},
    )
    assert resp.status_code == 400


def test_expiries_no_provider_returns_503(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["made-up-region"]),
    )
    monkeypatch.setattr(
        "services.options.dispatcher.get_options_provider_or_none",
        lambda r: None,
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/expiries",
        query_string={"apikey": "x", "underlying": "AAPL"},
    )
    assert resp.status_code == 503
    err = resp.get_json()["error"]
    assert err["code"] == "options_provider_not_registered"


def test_chain_us_region_returns_calls_and_puts(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["us"]),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/chain",
        query_string={"apikey": "x", "underlying": "AAPL",
                       "expiry": "2026-05-15"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["underlying"] == "AAPL"
    assert body["expiry"] == "2026-05-15"
    assert body["region_code"] == "us"
    assert len(body["calls"]) >= 1
    assert len(body["puts"]) >= 1
    sample = body["calls"][0]
    assert sample["right"] == "CALL"
    assert sample["currency"] == "USD"
    assert sample["lot_size"] == 100
    # Strike round-trips as decimal string.
    Decimal(sample["strike"])


def test_chain_missing_expiry_returns_400(flask_app, monkeypatch):
    _install_fake_auth_expiries(monkeypatch)
    resp = flask_app.test_client().get(
        "/api/v2/options/chain",
        query_string={"apikey": "x", "underlying": "AAPL"},
    )
    assert resp.status_code == 400


def test_chain_unauthorized_returns_401(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.options.resolve_auth",
        lambda: (None, None, "missing apikey"),
    )
    resp = flask_app.test_client().get(
        "/api/v2/options/chain",
        query_string={"underlying": "AAPL", "expiry": "2026-05-15"},
    )
    assert resp.status_code == 401
