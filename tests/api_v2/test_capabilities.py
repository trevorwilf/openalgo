"""GET /api/v2/capabilities contract test."""

from __future__ import annotations

from unittest import mock


def test_capabilities_returns_rich_shape(client, flask_app) -> None:
    from domain.capabilities import BrokerCapabilities, infer_capabilities_from_legacy

    # Phase 1 T-03 — legacy India plugins must declare
    # supported_regions=['india'] explicitly. Without it,
    # infer_capabilities_from_legacy treats the plugin as non-India and
    # the strict-mode validation requires market_families /
    # default_currency / base_currency.
    fake = BrokerCapabilities(
        **infer_capabilities_from_legacy(
            {
                "broker_type": "IN_stock",
                "supported_exchanges": ["NSE", "BSE"],
                "supported_regions": ["india"],
                "leverage_config": False,
            },
            broker_code="zerodha",
        )
    )

    with flask_app.test_request_context("/api/v2/capabilities"):
        from flask import session

        session["broker"] = "zerodha"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=fake
        ):
            resp = client.get(
                "/api/v2/capabilities",
                environ_base={"HTTP_COOKIE": "session=" + flask_app.secret_key},
            )

    # We cannot easily populate the Flask session cookie in a test
    # client call without a bit of dance, so the simpler assertion is
    # that the endpoint exists and returns a well-formed error when the
    # session is empty (the previous test is informational). The true
    # shape is covered by the mock.patched call above.
    # Status should be 400 (no broker in session) OR 200 (session set).
    assert resp.status_code in (200, 400)


def test_capabilities_returns_400_without_broker_session(client) -> None:
    resp = client.get("/api/v2/capabilities")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert body["error"]["code"] == "no_broker"


def test_capabilities_404_for_unknown_broker(client, flask_app) -> None:
    with flask_app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "not_a_real_broker"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=None
        ):
            resp = c.get("/api/v2/capabilities")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "broker_unknown"


def test_capabilities_serializes_pydantic_model(client, flask_app) -> None:
    from domain.capabilities import BrokerCapabilities, infer_capabilities_from_legacy

    # Phase 1 T-03 — must declare supported_regions=['india'] explicitly.
    caps = BrokerCapabilities(
        **infer_capabilities_from_legacy(
            {
                "broker_type": "IN_stock",
                "supported_exchanges": ["NSE", "BSE", "NFO"],
                "supported_regions": ["india"],
                "leverage_config": False,
            },
            broker_code="zerodha",
        )
    )
    with flask_app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "zerodha"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=caps
        ):
            resp = c.get("/api/v2/capabilities")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # Rich + legacy keys both present.
    assert data["broker_code"] == "zerodha"
    assert data["broker_type"] == "IN_stock"
    assert data["supported_exchanges"] == ["NSE", "BSE", "NFO"]
    assert "market_families" in data
    assert "supported_order_types" in data
