"""/api/v2/orders — translate normalized request to legacy Indian fields
and confirm broker dispatch matches v1.

For each legacy (product, pricetype) combo, issue the v2-normalized
equivalent and assert the place_order service sees the same outbound
payload.
"""

from __future__ import annotations

from unittest import mock

import pytest


def _mock_auth():
    return mock.patch(
        "restx_api.v2._auth.get_auth_token_broker",
        return_value=("fake-auth", None, "zerodha"),
    )


def _call(client, body):
    with _mock_auth(), mock.patch(
        "services.place_order_service.place_order_with_auth",
        return_value=(
            True,
            {"orderid": "TEST42", "order_status": "submitted"},
            200,
        ),
    ) as patched:
        resp = client.post("/api/v2/orders", json=body)
    return resp, patched


def _base_normalized(**overrides):
    body = {
        "apikey": "fake",
        "instrument": {"venue_code": "NSE", "canonical_symbol": "RELIANCE"},
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "time_in_force": "DAY",
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    "ot,expected_pricetype",
    [
        ("MARKET", "MARKET"),
        ("LIMIT", "LIMIT"),
        ("STOP_LIMIT", "SL"),
        ("STOP", "SL-M"),
    ],
)
def test_normalized_order_type_translates_to_legacy_pricetype(
    client, ot, expected_pricetype
) -> None:
    body = _base_normalized(order_type=ot)
    if ot in ("LIMIT", "STOP_LIMIT"):
        body["price"] = "100"
    if ot in ("STOP", "STOP_LIMIT"):
        body["trigger_price"] = "99"

    resp, patched = _call(client, body)
    assert resp.status_code == 200, resp.get_json()
    assert patched.call_count == 1
    _, kwargs = patched.call_args
    order_data = kwargs["order_data"]
    assert order_data["price_type"] == expected_pricetype


def test_reduce_only_effect_maps_to_MIS(client) -> None:
    body = _base_normalized(position_effect="REDUCE_ONLY")
    resp, patched = _call(client, body)
    assert resp.status_code == 200
    order_data = patched.call_args.kwargs["order_data"]
    assert order_data["product_type"] == "MIS"


def test_default_position_effect_maps_to_CNC(client) -> None:
    resp, patched = _call(client, _base_normalized())
    assert resp.status_code == 200
    assert patched.call_args.kwargs["order_data"]["product_type"] == "CNC"


def test_unsupported_order_type_returns_422(client) -> None:
    with _mock_auth():
        resp = client.post(
            "/api/v2/orders",
            json=_base_normalized(
                order_type="MARKET_ON_OPEN", time_in_force="OPG"
            ),
        )
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"]["code"] == "unsupported_capability"
    assert "MARKET_ON_OPEN" in body["error"]["message"]


def test_unsupported_tif_returns_422(client) -> None:
    with _mock_auth():
        resp = client.post(
            "/api/v2/orders", json=_base_normalized(time_in_force="GTC"),
        )
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "unsupported_capability"


def test_validation_error_returns_422(client) -> None:
    with _mock_auth():
        resp = client.post(
            "/api/v2/orders",
            json=_base_normalized(
                order_type="LIMIT"
                # missing required price
            ),
        )
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_successful_order_envelope(client) -> None:
    resp, _ = _call(client, _base_normalized())
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["order_id"] == "TEST42"
    assert body["status"] == "submitted"
    assert body["instrument"]["venue_code"] == "NSE"
    assert body["instrument"]["canonical_symbol"] == "RELIANCE"
    # Legacy payload preserved for audit.
    assert body["legacy"]["orderid"] == "TEST42"
