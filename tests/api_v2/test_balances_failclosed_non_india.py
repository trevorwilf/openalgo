"""Phase 5 v4 (ADR 0023, invariant 5) — /api/v2/balances fail-closed
when no BrokerBalanceAdapter is registered for a non-India broker.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


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
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    _install_fake_auth(monkeypatch, "fake_nonindia")
    _stub_caps(monkeypatch, ["us"])

    resp = flask_app.test_client().get("/api/v2/balances")
    assert resp.status_code == 503, resp.get_json()
    body = resp.get_json()
    assert body["error"]["code"] == "promoted_capability_unavailable"
    assert body["error"]["details"]["sub_code"] == "balance_adapter_not_registered"


def test_non_india_with_adapter_returns_normalized_balance(flask_app, monkeypatch):
    from broker._mock_webull_like.api.position_balance_adapters import (
        install_mock_webull_like_account_adapters,
    )
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    install_mock_webull_like_account_adapters()
    _install_fake_auth(monkeypatch, "_mock_webull_like")
    _stub_caps(monkeypatch, ["us"])

    resp = flask_app.test_client().get("/api/v2/balances")
    assert resp.status_code == 200, resp.get_json()
    balance = resp.get_json()["data"]["balance"]
    assert balance["cash"] == "50000.00"
    assert balance["equity"] == "54920.00"
    assert balance["currency"] == "USD"


def test_india_broker_uses_legacy_funds_path(flask_app, monkeypatch):
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )

    clear_market_data_registries_for_tests()
    _install_fake_auth(monkeypatch, "zerodha")
    _stub_caps(monkeypatch, ["india"])

    fake_resp = (True, {"data": {"availablecash": "100000"}}, 200)
    with patch(
        "services.funds_service.get_funds_with_auth",
        return_value=fake_resp,
    ):
        resp = flask_app.test_client().get("/api/v2/balances")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["balances"] == {"availablecash": "100000"}
