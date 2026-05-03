"""Alpaca funds / margin data — framework hook.

The framework's ``services.funds_service`` imports
``broker.<broker>.api.funds`` and calls ``get_margin_data(auth_token)``
to populate the dashboard funds widget. This module is the Alpaca
shim that:

  1. Rebuilds an :class:`AlpacaAuth` from the JSON token emitted by
     :func:`broker.alpaca.api.auth_api.authenticate_broker`.
  2. Hits ``GET /v2/account`` to fetch the canonical balance fields.
  3. Maps Alpaca's account schema onto OpenAlgo's funds-widget keys.

OpenAlgo's funds-widget schema (per the Zerodha reference):

    {
      "availablecash":   <available cash, string with 2 decimals>,
      "collateral":      <pledged collateral; 0 for US brokers>,
      "m2munrealized":   <unrealized P&L; from /v2/account.equity vs cash>,
      "m2mrealized":     <realized P&L; from /v2/account fields>,
      "utiliseddebits":  <margin / debits used>,
    }

Alpaca's /v2/account gives us cash + equity + buying_power directly.
m2m unrealized derives from (long_market_value + short_market_value);
m2m realized requires the orders endpoint (deferred — we surface 0
for now). The dashboard widget renders strings, so all values are
formatted to 2 decimals.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, auth_handle_from_token
from utils.logging import get_logger

logger = get_logger(__name__)


def _coerce_decimal(raw: Any) -> Decimal:
    if raw is None or raw == "":
        return Decimal("0")
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return Decimal("0")


def get_margin_data(auth_token: str) -> dict[str, str]:
    """Fetch account funds from Alpaca's ``/v2/account`` endpoint and
    map onto OpenAlgo's funds-widget shape.

    Returns an empty dict on any error so the dashboard renders a
    "no funds" state rather than crashing the page. Detailed errors
    go to the log.
    """
    try:
        auth: AlpacaAuth = auth_handle_from_token(auth_token)
    except Exception:  # noqa: BLE001 - boundary
        logger.exception("Alpaca: invalid auth_token; cannot fetch funds")
        return {}

    try:
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            resp = client.get("/v2/account")
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        logger.exception("Alpaca /v2/account request failed: %s", exc)
        return {}

    cash = _coerce_decimal(body.get("cash"))
    equity = _coerce_decimal(body.get("equity"))
    last_equity = _coerce_decimal(body.get("last_equity"))
    long_mv = _coerce_decimal(body.get("long_market_value"))
    short_mv = _coerce_decimal(body.get("short_market_value"))

    # Unrealized = current equity − (cash + cost basis approximation).
    # Since /v2/account doesn't carry per-position cost basis, use the
    # standard Alpaca derivation: long_market_value + short_market_value
    # is the position MV; subtracting that from (equity - cash) gives
    # an approximation of the unrealized component when positions are
    # priced at last trade. For accounts without open positions this
    # collapses to 0.
    position_mv = long_mv + short_mv
    available_cash = cash
    # ``equity - last_equity`` is intraday P&L — a useful proxy when
    # Alpaca doesn't expose explicit unrealized fields at the account
    # level. Fail-soft: if last_equity is 0/missing, surface 0.
    intraday_pnl = (equity - last_equity) if last_equity > 0 else Decimal("0")
    # Margin used = total equity exposure − cash bucket. Floors at 0
    # to avoid negative display when account is fully cash.
    used = max(Decimal("0"), position_mv)

    return {
        "availablecash": f"{available_cash:.2f}",
        "collateral": "0.00",  # Alpaca has no pledged-collateral concept.
        "m2munrealized": f"{intraday_pnl:.2f}",
        "m2mrealized": "0.00",  # /v2/account doesn't carry realized P&L.
        "utiliseddebits": f"{used:.2f}",
    }


__all__ = ["get_margin_data"]
