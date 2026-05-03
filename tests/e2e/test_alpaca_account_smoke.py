"""Alpaca paper-API account smoke (read-only).

Lighter sibling to ``test_alpaca_smoke.py``: this test only hits
``GET /v2/account`` and asserts the response shape. No orders placed,
no positions modified.

Gated on ``ALPACA_E2E=1`` plus credentials. Without all three the
module is skipped so CI stays green without keys.
"""

from __future__ import annotations

import os

import httpx
import pytest

_ANY_KEY_AVAILABLE = (
    (os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET"))
    or (os.environ.get("BROKER_API_KEY") and os.environ.get("BROKER_API_SECRET"))
    or (
        os.environ.get("ALPACA_LIVE_MODE") == "1"
        and os.environ.get("BROKER_API_KEY_MARKET")
        and os.environ.get("BROKER_API_SECRET_MARKET")
    )
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ALPACA_E2E") != "1" or not _ANY_KEY_AVAILABLE,
    reason=(
        "Live Alpaca account smoke — set ALPACA_E2E=1 and supply either "
        "ALPACA_API_KEY/ALPACA_API_SECRET or "
        "BROKER_API_KEY/BROKER_API_SECRET (paper) or "
        "BROKER_API_KEY_MARKET/BROKER_API_SECRET_MARKET (live, plus "
        "ALPACA_LIVE_MODE=1)."
    ),
)


def test_alpaca_account_endpoint_returns_active_account():
    from broker.alpaca.api.auth_api import authenticate

    auth = authenticate()
    with httpx.Client(
        base_url=auth.base_url,
        headers=dict(auth.headers),
        timeout=httpx.Timeout(10.0, connect=5.0),
    ) as client:
        resp = client.get("/v2/account")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Required fields per Alpaca's documented Account object.
    for field in ("id", "account_number", "status", "currency", "cash", "buying_power"):
        assert field in body, f"missing {field} in /v2/account response"

    # Account should not be in a hard-blocked state for a smoke test
    # to be meaningful.
    assert not body.get("account_blocked"), "account is account_blocked"
    assert body.get("currency") == "USD"
