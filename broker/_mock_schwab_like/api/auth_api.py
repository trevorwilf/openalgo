"""Mock Schwab-LIKE auth — deterministic in-memory test fixture.

NOT a real Schwab OAuth flow. Returns a fixed AccountContext with a
Schwab-style account_hash. Tests that need a real broker session
should patch ``authenticate``.
"""

from __future__ import annotations

import os
from typing import Any

from domain.account_context import AccountContext
from domain.currency import Currency

BROKER_CODE = "_mock_schwab_like"


def load_credentials() -> dict[str, Any]:
    """Return deterministic test credentials.

    Reads from env vars (MOCK_SCHWAB_TOKEN, MOCK_SCHWAB_REFRESH) when
    set; otherwise returns hardcoded fixtures so the harness can run
    with no env setup.
    """
    return {
        "access_token": os.environ.get("MOCK_SCHWAB_TOKEN", "MOCK_SCHWAB_TOKEN_X"),
        "refresh_token": os.environ.get(
            "MOCK_SCHWAB_REFRESH", "MOCK_SCHWAB_REFRESH_Y"
        ),
        "expires_at": "2099-01-01T00:00:00Z",
    }


def authenticate(_credentials: dict[str, Any] | None = None) -> AccountContext:
    """Return an AccountContext for the mock account.

    No HTTP, no OAuth dance. The shape proves the framework can model
    Schwab-style account_hash + entitlements without ad-hoc dicts.
    """
    return AccountContext(
        broker_code=BROKER_CODE,
        account_id="MOCK-SCHWAB-ACCOUNT-001",
        account_hash="MOCK_HASH_AAAA1111",
        base_currency=Currency.USD,
        entitlements=["us_equity_realtime", "options_l2"],
    )


__all__ = ["BROKER_CODE", "authenticate", "load_credentials"]
