"""Alpaca funds / margin data — framework hook.

The framework's ``services.funds_service`` imports
``broker.<broker>.api.funds`` and calls ``get_margin_data(auth_token)``
to populate the dashboard funds widget. This module is the Alpaca
shim that:

  1. Rebuilds an :class:`AlpacaAuth` from the JSON token emitted by
     :func:`broker.alpaca.api.auth_api.authenticate_broker`.
  2. Hits ``GET /v2/account`` and ``GET /v2/positions`` to fetch
     account-level balances and per-position unrealized P&L.
  3. Maps Alpaca's account schema onto OpenAlgo's funds-widget keys.

OpenAlgo's funds-widget schema (per the Zerodha reference):

    {
      "availablecash":   <available cash, string with 2 decimals>,
      "collateral":      <pledged collateral; 0 for US brokers>,
      "m2munrealized":   <unrealized intraday P&L>,
      "m2mrealized":     <realized intraday P&L>,
      "utiliseddebits":  <margin / debits used>,
    }

Alpaca's /v2/account doesn't expose realized P&L directly. We derive
the unrealized component from the per-position
``unrealized_intraday_pl`` field on /v2/positions, then back into
realized via ``(equity - last_equity) - unrealized_intraday``. This
is approximate — it implicitly assumes no intraday cash deposits or
withdrawals — which is correct for paper accounts and a fine
approximation for live accounts during a trading session.

The dashboard widget renders strings, so all values are formatted to
2 decimals.
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
            # Pulling positions to back out realized intraday P&L.
            # Failure here is non-fatal — we still return the account
            # snapshot with realized=0 rather than dropping the whole
            # widget.
            try:
                pos_resp = client.get("/v2/positions")
                pos_resp.raise_for_status()
                positions = pos_resp.json() or []
            except httpx.HTTPError as exc:
                logger.warning("Alpaca /v2/positions request failed (m2mrealized will be 0.00): %s", exc)
                positions = []
    except httpx.HTTPError as exc:
        logger.exception("Alpaca /v2/account request failed: %s", exc)
        return {}

    cash = _coerce_decimal(body.get("cash"))
    equity = _coerce_decimal(body.get("equity"))
    last_equity = _coerce_decimal(body.get("last_equity"))
    long_mv = _coerce_decimal(body.get("long_market_value"))
    short_mv = _coerce_decimal(body.get("short_market_value"))

    unrealized_intraday = sum(
        (_coerce_decimal(p.get("unrealized_intraday_pl")) for p in positions),
        Decimal("0"),
    )

    # Gross position exposure (used to populate the funds-widget's
    # "utiliseddebits" margin-used field).
    #
    # Alpaca's ``/v2/account`` reports ``short_market_value`` as a
    # NEGATIVE number (the value owed on short positions, per their
    # API docs). Naively summing ``long_mv + short_mv`` would NET the
    # short exposure against the long exposure, understating the
    # margin actually committed by short positions. We want gross
    # exposure (long-side dollars + short-side dollars), so we take
    # the absolute value of the short component before adding.
    #
    # Concrete example: long $10k AAPL, short $5k MSFT →
    #   long_mv = 10000, short_mv = -5000
    #   naive (buggy):   position_mv = 5000   (under-reports margin)
    #   correct (gross): position_mv = 15000
    position_mv = long_mv + abs(short_mv)
    available_cash = cash
    # ``equity - last_equity`` is total intraday P&L (realized +
    # unrealized). Subtracting per-position unrealized_intraday_pl
    # gives realized intraday P&L. Fail-soft: if last_equity is 0/
    # missing, surface zeros.
    if last_equity > 0:
        intraday_pnl_total = equity - last_equity
        m2m_realized = intraday_pnl_total - unrealized_intraday
    else:
        intraday_pnl_total = Decimal("0")
        m2m_realized = Decimal("0")
    # Margin used = total equity exposure − cash bucket. Floors at 0
    # to avoid negative display when account is fully cash.
    used = max(Decimal("0"), position_mv)

    return {
        "availablecash": f"{available_cash:.2f}",
        "collateral": "0.00",  # Alpaca has no pledged-collateral concept.
        "m2munrealized": f"{unrealized_intraday:.2f}",
        "m2mrealized": f"{m2m_realized:.2f}",
        "utiliseddebits": f"{used:.2f}",
    }


__all__ = ["get_margin_data"]
