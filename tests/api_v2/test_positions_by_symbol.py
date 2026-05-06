"""GET /api/v2/positions/<symbol> — single-symbol position lookup.

Migration target for /api/v1/openposition. Filters the broker's
positions list by canonical_symbol; returns 404 when flat.
"""
from __future__ import annotations

from decimal import Decimal

import pytest


def _install_fake_auth(monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.accounts.resolve_auth",
        lambda: ("fake-token", "alpaca", None),
    )


def test_positions_by_symbol_hit_returns_record(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)

    class _StubPos:
        def __init__(self, sym, qty):
            self.instrument_id = "abc-123"
            self.venue_code = "XNAS"
            self.canonical_symbol = sym
            self.quantity = Decimal(qty)
            self.average_price = Decimal("281.41")
            self.market_value = Decimal("281.41")
            self.realized_pnl = None
            self.unrealized_pnl = Decimal("0.00")
            self.currency = "USD"

    class _Adapter:
        def get_positions(self, ctx):
            return [_StubPos("AAPL", "1"), _StubPos("MSFT", "5")]

    monkeypatch.setattr(
        "services.broker_market_data_registry.get_broker_position_adapter",
        lambda b: _Adapter(),
    )

    resp = flask_app.test_client().get(
        "/api/v2/positions/AAPL", query_string={"apikey": "x"},
    )
    assert resp.status_code == 200, resp.get_json()
    pos = resp.get_json()["data"]["position"]
    assert pos["canonical_symbol"] == "AAPL"
    assert pos["quantity"] == "1"
    assert pos["currency"] == "USD"


def test_positions_by_symbol_miss_returns_404(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)

    class _Adapter:
        def get_positions(self, ctx):
            return []  # account is flat

    monkeypatch.setattr(
        "services.broker_market_data_registry.get_broker_position_adapter",
        lambda b: _Adapter(),
    )

    resp = flask_app.test_client().get(
        "/api/v2/positions/AAPL", query_string={"apikey": "x"},
    )
    assert resp.status_code == 404
    err = resp.get_json()["error"]
    assert err["code"] == "not_found"
    assert err["details"]["canonical_symbol"] == "AAPL"


def test_positions_by_symbol_case_insensitive(flask_app, monkeypatch):
    _install_fake_auth(monkeypatch)

    class _Pos:
        def __init__(self, sym):
            self.instrument_id = "x"; self.venue_code = "XNAS"
            self.canonical_symbol = sym
            self.quantity = Decimal("1"); self.average_price = None
            self.market_value = None; self.realized_pnl = None
            self.unrealized_pnl = None; self.currency = "USD"

    class _Adapter:
        def get_positions(self, ctx):
            return [_Pos("AAPL")]

    monkeypatch.setattr(
        "services.broker_market_data_registry.get_broker_position_adapter",
        lambda b: _Adapter(),
    )

    # lowercase URL still finds AAPL
    resp = flask_app.test_client().get(
        "/api/v2/positions/aapl", query_string={"apikey": "x"},
    )
    assert resp.status_code == 200


def test_positions_by_symbol_no_adapter_non_india_fails_closed(
    flask_app, monkeypatch,
):
    _install_fake_auth(monkeypatch)
    monkeypatch.setattr(
        "services.broker_market_data_registry.get_broker_position_adapter",
        lambda b: None,
    )
    # Stub plugin caps to look like a non-India broker.
    from types import SimpleNamespace
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(
            supported_regions=["us"], broker_type="US_stock", base_currency=None,
        ),
    )

    resp = flask_app.test_client().get(
        "/api/v2/positions/AAPL", query_string={"apikey": "x"},
    )
    assert resp.status_code == 503
    assert resp.get_json()["error"]["details"]["sub_code"]


def test_positions_by_symbol_unauthorized_returns_401(flask_app, monkeypatch):
    monkeypatch.setattr(
        "restx_api.v2.accounts.resolve_auth",
        lambda: (None, None, "missing apikey"),
    )
    resp = flask_app.test_client().get("/api/v2/positions/AAPL")
    assert resp.status_code == 401
