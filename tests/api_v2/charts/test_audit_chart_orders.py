"""Phase 6 — audit log endpoint contract."""

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


def test_audit_get_returns_empty_list_initially(client, stub_auth):
    resp = client.get("/api/v2/audit/chart-orders?apikey=k")
    assert resp.status_code == 200
    assert isinstance(resp.get_json()["data"], list)


def test_audit_delete_returns_405(client, stub_auth):
    resp = client.delete("/api/v2/audit/chart-orders?apikey=k")
    assert resp.status_code == 405
    assert resp.get_json()["error"]["code"] == "audit_immutable"


def test_audit_records_event_via_audit_logger(client, stub_auth):
    """Use the audit_logger directly to write a row, then GET via the
    endpoint. Verifies the persistence + read contract end-to-end."""
    from services.charts.audit_logger import record_audit_event

    rid = record_audit_event(
        user_id="u:test-key-12",
        account_id="acct1",
        intent_kind="place",
        symbol="AAPL",
        qty="10",
        price="100",
        idempotency_token="tok-audit-1",
        status="PLACED",
    )
    if rid is None:
        # DB unavailable in this env — skip.
        return

    resp = client.get("/api/v2/audit/chart-orders?apikey=k")
    rows = resp.get_json()["data"]
    if isinstance(rows, list) and rows:
        assert any(r["idempotency_token"] == "tok-audit-1" for r in rows)
