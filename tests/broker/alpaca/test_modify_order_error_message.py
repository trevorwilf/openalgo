"""Regression: ``modify_order`` shim surfaces Alpaca's structured
JSON error body instead of returning raw HTTP text.

Previously ``modify_order`` returned ``r.text[:500]`` on 4xx —
operators saw the raw HTTP envelope (often HTML for 429 / 503) and
the broker's actual diagnostic ("cannot replace order in accepted
status", code 42210000) was lost. The neighbour ``cancel_order``
already does this correctly; the two shims now agree.
"""

from __future__ import annotations

import json

import httpx

from broker.alpaca.api.auth_api import PAPER_BASE_URL, DATA_BASE_URL
from broker.alpaca.api.order_api import modify_order


def _token() -> str:
    return json.dumps(
        {
            "api_key": "ak",
            "api_secret": "sk",
            "is_paper": True,
            "base_url": PAPER_BASE_URL,
            "data_base_url": DATA_BASE_URL,
        }
    )


def test_modify_order_surfaces_alpaca_message_on_422(monkeypatch):
    def _fake_patch(self, url, *args, **kwargs):
        return httpx.Response(
            422,
            json={
                "code": 42210000,
                "message": "cannot replace order in accepted status",
            },
            request=httpx.Request("PATCH", f"{PAPER_BASE_URL}{url}"),
        )

    monkeypatch.setattr(httpx.Client, "patch", _fake_patch)

    resp, status = modify_order(
        {"orderid": "abc-123", "price": "175.00"}, _token()
    )
    assert status == 422
    assert resp["status"] == "error"
    assert "cannot replace order in accepted status" in resp["message"]
    assert "42210000" in resp["message"]


def test_modify_order_falls_back_to_raw_text_on_non_json(monkeypatch):
    """Some upstream errors return HTML (Cloudflare 429 page, etc.)."""

    def _fake_patch(self, url, *args, **kwargs):
        return httpx.Response(
            503,
            content=b"<html>503 Service Unavailable</html>",
            request=httpx.Request("PATCH", f"{PAPER_BASE_URL}{url}"),
        )

    monkeypatch.setattr(httpx.Client, "patch", _fake_patch)

    resp, status = modify_order(
        {"orderid": "abc-123", "price": "175.00"}, _token()
    )
    assert status == 503
    assert "503" in resp["message"] or "Service Unavailable" in resp["message"]


def test_modify_order_no_modifiable_fields_returns_400():
    resp, status = modify_order({"orderid": "abc"}, _token())
    assert status == 400
    assert "no modifiable fields" in resp["message"]
