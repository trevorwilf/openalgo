"""Alpaca authentication — header-based key pair (no OAuth).

Two env vars drive it:

- ``ALPACA_API_KEY`` (APCA-API-KEY-ID)
- ``ALPACA_API_SECRET`` (APCA-API-SECRET-KEY)

There is no token refresh flow — keys are long-lived. The base URL is
selected by ``ALPACA_PAPER`` (default ``1``): paper vs live.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"


@dataclass(frozen=True)
class AlpacaAuth:
    """Opaque auth handle — headers ready for every Alpaca call."""

    base_url: str
    data_base_url: str
    headers: Mapping[str, str]

    @property
    def is_paper(self) -> bool:
        return self.base_url == PAPER_BASE_URL


def load_credentials() -> tuple[str, str, bool]:
    """Read API credentials from environment.

    Returns ``(api_key, api_secret, is_paper)``. Raises
    ``ValueError`` if either key is missing.
    """
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise ValueError(
            "ALPACA_API_KEY and ALPACA_API_SECRET must both be set"
        )
    is_paper = os.environ.get("ALPACA_PAPER", "1") != "0"
    return key, secret, is_paper


def authenticate() -> AlpacaAuth:
    """Return an :class:`AlpacaAuth` handle ready for API calls.

    No network call is made here — Alpaca's key-pair auth is purely
    header-based. Key validity is confirmed later when the account
    endpoint is hit.
    """
    key, secret, is_paper = load_credentials()
    base = PAPER_BASE_URL if is_paper else LIVE_BASE_URL
    return AlpacaAuth(
        base_url=base,
        data_base_url=DATA_BASE_URL,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
        },
    )


__all__ = [
    "AlpacaAuth",
    "DATA_BASE_URL",
    "LIVE_BASE_URL",
    "PAPER_BASE_URL",
    "authenticate",
    "load_credentials",
]
