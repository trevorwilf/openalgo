"""Alpaca authentication — header-based key pair (no OAuth).

Two precedence-ordered credential sources:

1. **Explicit Alpaca-prefixed env vars** (recommended for multi-broker
   shared environments):

       ALPACA_API_KEY      (APCA-API-KEY-ID)
       ALPACA_API_SECRET   (APCA-API-SECRET-KEY)
       ALPACA_PAPER=1      (default — paper-api.alpaca.markets)
       ALPACA_PAPER=0      (live — api.alpaca.markets)

2. **Generic OpenAlgo BROKER_API_* convention** (used when an
   OpenAlgo deployment dedicates the single ``BROKER`` slot to
   Alpaca). Paper keys go in the regular slots, live keys in the
   ``_MARKET`` slots:

       BROKER_API_KEY            (paper key)
       BROKER_API_SECRET         (paper secret)
       BROKER_API_KEY_MARKET     (live key)
       BROKER_API_SECRET_MARKET  (live secret)
       ALPACA_LIVE_MODE=1        → use _MARKET pair + live URL
       ALPACA_LIVE_MODE=0        → use regular pair + paper URL (default)

If both source families are populated, the explicit
``ALPACA_API_KEY/ALPACA_API_SECRET`` pair wins. If neither is set
``load_credentials`` raises ``ValueError``.

There is no token refresh flow — keys are long-lived. Key validity
is confirmed later when the account endpoint is hit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"


# Sentinel placeholder values that the .sample.env ships and that
# users sometimes leave unchanged. Treating them as "missing" gives
# a clearer error than letting them through to the broker.
_PLACEHOLDER_VALUES = frozenset({
    "",
    "YOUR_BROKER_API_KEY",
    "YOUR_BROKER_API_SECRET",
    "YOUR_BROKER_MARKET_API_KEY",
    "YOUR_BROKER_MARKET_API_SECRET",
    "YOUR_ALPACA_API_KEY",
    "YOUR_ALPACA_API_SECRET",
})


def _is_real(value: str | None) -> bool:
    return bool(value) and value not in _PLACEHOLDER_VALUES


def _resolve_is_paper() -> bool:
    """Determine paper vs live mode.

    ``ALPACA_LIVE_MODE`` takes precedence (1 → live; anything else →
    paper). When unset, fall back to ``ALPACA_PAPER`` (0 → live;
    anything else → paper). Default is paper.
    """
    live_mode = os.environ.get("ALPACA_LIVE_MODE")
    if live_mode is not None:
        return live_mode.strip().lower() not in ("1", "true", "yes", "on")
    paper = os.environ.get("ALPACA_PAPER")
    if paper is not None:
        return paper.strip() != "0"
    return True


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
    ``ValueError`` if no credential pair can be resolved for the
    chosen mode.
    """
    is_paper = _resolve_is_paper()

    # Source 1: explicit Alpaca-prefixed (always wins when set).
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")

    if not (_is_real(key) and _is_real(secret)):
        # Source 2: generic BROKER_API_* convention.
        if is_paper:
            key = os.environ.get("BROKER_API_KEY")
            secret = os.environ.get("BROKER_API_SECRET")
            slot_label = "BROKER_API_KEY/BROKER_API_SECRET"
        else:
            key = os.environ.get("BROKER_API_KEY_MARKET")
            secret = os.environ.get("BROKER_API_SECRET_MARKET")
            slot_label = "BROKER_API_KEY_MARKET/BROKER_API_SECRET_MARKET"

        if not (_is_real(key) and _is_real(secret)):
            mode_label = "paper" if is_paper else "live"
            raise ValueError(
                f"Alpaca {mode_label} credentials missing. Set either "
                "ALPACA_API_KEY/ALPACA_API_SECRET (with ALPACA_PAPER "
                "controlling mode) or "
                f"{slot_label} (with ALPACA_LIVE_MODE controlling mode)."
            )

    return key, secret, is_paper  # type: ignore[return-value]


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
