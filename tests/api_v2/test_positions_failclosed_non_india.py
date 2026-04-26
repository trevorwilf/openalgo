"""Phase 5 v4 (ADR 0023, invariant 5) — /api/v2/positions fail-closed
when no BrokerPositionAdapter is registered for a non-India broker.

India broker continues to proxy to the legacy
``services.positions_service.get_positions_with_auth`` (preserved).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _install_fake_auth(monkeypatch, broker_code: str):
    def _fake():
        return "fake-token", broker_code, None

    monkeypatch.setattr("restx_api.v2.accounts.resolve_auth", _fake)


def _stub_caps(monkeypatch, regions):
    caps = SimpleNamespace(supported_regions=regions)
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda broker: caps,
    )


def test_non_india_no_adapter_returns_503(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_FAKE_NONINDIA", "1")
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    _install_fake_auth(monkeypatch, "fake_nonindia")
    _stub_caps(monkeypatch, ["us"])

    resp = flask_app.test_client().get("/api/v2/positions")
    assert resp.status_code == 503, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "promoted_capability_unavailable"
    assert body["error"]["details"]["sub_code"] == "position_adapter_not_registered"
    assert body["error"]["details"]["broker_code"] == "fake_nonindia"


def test_non_india_with_adapter_returns_normalized_positions(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_MOCK_SCHWAB_LIKE", "1")
    from broker._mock_schwab_like.api.position_balance_adapters import (
        install_mock_schwab_like_account_adapters,
    )
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    install_mock_schwab_like_account_adapters()
    _install_fake_auth(monkeypatch, "_mock_schwab_like")
    _stub_caps(monkeypatch, ["us"])

    resp = flask_app.test_client().get("/api/v2/positions")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]["positions"]
    assert len(data) == 2
    aapl = next(p for p in data if p["canonical_symbol"] == "AAPL")
    assert aapl["venue_code"] == "XNAS"
    assert aapl["quantity"] == "10"
    assert aapl["currency"] == "USD"


def test_india_broker_uses_legacy_path(flask_app, monkeypatch):
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    _install_fake_auth(monkeypatch, "zerodha")
    _stub_caps(monkeypatch, ["india"])

    fake_resp = (True, {"data": [{"symbol": "INFY", "quantity": 10}]}, 200)
    with patch(
        "services.positionbook_service.get_positionbook_with_auth",
        return_value=fake_resp,
    ):
        resp = flask_app.test_client().get("/api/v2/positions")

    assert resp.status_code == 200
    data = resp.get_json()["data"]["positions"]
    assert data == [{"symbol": "INFY", "quantity": 10}]
