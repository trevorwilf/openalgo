"""Phase 7 — /api/v2/admin/broker_compliance endpoint smoke test."""

from __future__ import annotations

import pytest


def test_compliance_endpoint_returns_matrix(flask_app):
    resp = flask_app.test_client().get("/api/v2/admin/broker_compliance")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "matrix" in body["data"]
    # The shipped doc has alpaca + zerodha + dhan + deltaexchange.
    brokers = {row["broker"] for row in body["data"]["matrix"]}
    assert "alpaca" in brokers


def test_alpaca_row_has_pass_for_all_strict_contracts(flask_app):
    resp = flask_app.test_client().get("/api/v2/admin/broker_compliance")
    body = resp.get_json()
    rows = {r["broker"]: r for r in body["data"]["matrix"]}
    assert "alpaca" in rows
    contracts = rows["alpaca"]["contracts"]
    # Strict contracts from the shipped matrix doc.
    for name in ("metadata", "auth", "account", "translator", "lane_isolation", "fail_closed"):
        assert contracts[name] == "pass", f"alpaca {name} = {contracts[name]}"
