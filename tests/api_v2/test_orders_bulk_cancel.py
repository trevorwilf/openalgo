"""DELETE /api/v2/orders — bulk cancel-all for the authenticated session.

Mirrors the pattern in test_promoted_orders_alpaca.py: register an
AlpacaOrderTranslator with a mocked HTTP client so the test exercises
the real translator + dispatcher without hitting the network.
"""

from __future__ import annotations

import httpx
import pytest

from broker.alpaca.api.auth_api import AlpacaAuth, DATA_BASE_URL, PAPER_BASE_URL
from broker.alpaca.api.order_api import AlpacaOrderTranslator
from services.broker_translator_registry import (
    clear_registry_for_tests,
    register_broker_translator,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _paper_auth() -> AlpacaAuth:
    return AlpacaAuth(
        base_url=PAPER_BASE_URL,
        data_base_url=DATA_BASE_URL,
        headers={"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"},
    )


def _install_fake_auth_resolver(monkeypatch):
    def fake_resolve_auth():
        return "fake-token", "alpaca", None

    monkeypatch.setattr("restx_api.v2.orders.resolve_auth", fake_resolve_auth)


def _orders_client(handler) -> httpx.Client:
    auth = _paper_auth()
    return httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        transport=httpx.MockTransport(handler),
    )


def test_bulk_cancel_returns_canceled_and_failed_lists(flask_app, monkeypatch):
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)

    multi_status = [
        {"id": "alp-1", "status": 200, "body": {}},
        {"id": "alp-2", "status": 200, "body": {}},
        {"id": "alp-3", "status": 422, "body": {"message": "not cancelable"}},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/orders":
            return httpx.Response(207, json=multi_status)
        return httpx.Response(404, json={"message": "not found"})

    auth = _paper_auth()
    client = _orders_client(handler)
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().delete("/api/v2/orders")
    client.close()

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["summary"] == {"canceled_count": 2, "failed_count": 1}
    canceled_ids = {row["order_id"] for row in body["canceled"]}
    assert canceled_ids == {"alp-1", "alp-2"}
    failed = body["failed"]
    assert len(failed) == 1
    assert failed[0]["order_id"] == "alp-3"


def test_bulk_cancel_returns_empty_when_no_open_orders(flask_app, monkeypatch):
    """Alpaca returns 204 No Content when nothing is open. The endpoint
    must surface that as ``(canceled=[], failed=[])`` with HTTP 200,
    not propagate the 204 (which would lose the canonical envelope)."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE" and req.url.path == "/v2/orders":
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "not found"})

    auth = _paper_auth()
    client = _orders_client(handler)
    register_broker_translator(AlpacaOrderTranslator(auth=auth, client=client))

    resp = flask_app.test_client().delete("/api/v2/orders")
    client.close()

    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["canceled"] == []
    assert body["failed"] == []
    assert body["summary"] == {"canceled_count": 0, "failed_count": 0}


def test_bulk_cancel_promoted_lane_required(flask_app, monkeypatch):
    """Without the per-broker promotion flag, the endpoint must return
    503 promoted_lane_required — same fail-closed behavior as the
    other order-management methods on this resource (GET / DELETE
    by-id)."""
    _install_fake_auth_resolver(monkeypatch)
    # Ensure the flag is OFF.
    monkeypatch.delenv("API_V2_ALPACA", raising=False)
    # Need a fake broker capability that says supports_regions=['india']
    # so the lane-check doesn't reject it as "non-India must use v2".
    from types import SimpleNamespace

    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda b: SimpleNamespace(supported_regions=["india"], broker_type="IN_stock"),
    )

    resp = flask_app.test_client().delete("/api/v2/orders")
    assert resp.status_code == 503, resp.get_json()
    assert resp.get_json()["error"]["code"] == "promoted_lane_required"


def test_bulk_cancel_unimplemented_when_translator_lacks_method(flask_app, monkeypatch):
    """Translators without ``cancel_all_orders_via_token`` get 501.
    Pin the contract so a future broker plugin doesn't silently get
    a 5xx if it forgets to implement the hook."""
    monkeypatch.setenv("API_V2_ALPACA", "1")
    _install_fake_auth_resolver(monkeypatch)

    class _StubTranslator:
        broker_code = "alpaca"
        # Deliberately no cancel_all_orders_via_token attribute.

    register_broker_translator(_StubTranslator())

    resp = flask_app.test_client().delete("/api/v2/orders")
    assert resp.status_code == 501
    body = resp.get_json()
    assert body["error"]["code"] == "unimplemented"
    assert "cancel_all_orders_via_token" in body["error"]["message"]
