"""v2 error envelope is structured: {error: {code, message, details}}.

Distinct from v1's {"status":"error", "message":"..."} shape so clients
can branch on `error.code`.
"""

from __future__ import annotations

from unittest import mock


def test_401_shape(client) -> None:
    # Unauthorized — no API key anywhere.
    resp = client.post("/api/v2/quotes", json={"instruments": []})
    assert resp.status_code == 401
    body = resp.get_json()
    # v1 shape: {"status":"error","message":...}. v2: {"error":{...}}
    assert "status" not in body
    assert "error" in body
    assert body["error"]["code"] == "unauthorized"
    assert "message" in body["error"]
    assert "details" in body["error"]


def test_400_shape(client) -> None:
    with mock.patch(
        "restx_api.v2._auth.get_auth_token_broker",
        return_value=("fake", None, "zerodha"),
    ):
        resp = client.post("/api/v2/quotes", json={"apikey": "fake"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert body["error"]["code"] == "bad_request"


def test_404_shape(client) -> None:
    resp = client.get("/api/v2/instruments/deadbeef-not-a-uuid")
    body = resp.get_json()
    assert "error" in body
    assert body["error"]["code"] == "bad_request"


def test_error_has_details_dict_by_default(client) -> None:
    resp = client.post("/api/v2/quotes", json={"instruments": []})
    body = resp.get_json()
    assert isinstance(body["error"]["details"], dict)
