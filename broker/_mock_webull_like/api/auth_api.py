"""Mock Webull-LIKE auth — deterministic in-memory test fixture.

NOT a real Webull SIGNATURE/OAuth flow. Returns a fixed
AccountContext with a Webull-style subaccount_id.
"""

from __future__ import annotations

import os
from typing import Any

from domain.account_context import AccountContext
from domain.currency import Currency

BROKER_CODE = "_mock_webull_like"


def load_credentials() -> dict[str, Any]:
    return {
        "api_key": os.environ.get("MOCK_WEBULL_API_KEY", "MOCK_WEBULL_KEY"),
        "api_secret": os.environ.get(
            "MOCK_WEBULL_API_SECRET", "MOCK_WEBULL_SECRET"
        ),
        "auth_mode": os.environ.get("MOCK_WEBULL_AUTH_MODE", "SIGNATURE"),
    }


def authenticate(_credentials: dict[str, Any] | None = None) -> AccountContext:
    return AccountContext(
        broker_code=BROKER_CODE,
        account_id="MOCK-WEBULL-PARENT-001",
        subaccount_id="MOCK_SUB_X",
        base_currency=Currency.USD,
        entitlements=["us_equity_realtime", "crypto_quotes"],
    )


__all__ = ["BROKER_CODE", "authenticate", "load_credentials"]
