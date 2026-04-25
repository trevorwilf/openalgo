"""Alpaca account endpoints: /v2/account and /v2/positions.

Return normalized shapes (:class:`NormalizedBalance`,
:class:`NormalizedPosition`) so the rest of the platform does not
branch on broker.

Only direct dependencies are httpx, the auth handle, and the
domain-level shapes — no legacy imports.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth
from domain.account import (
    NormalizedAccountSnapshot,
    NormalizedBalance,
    NormalizedPosition,
)
from domain.currency import Currency, CurrencyAmount
from domain.enums import AssetClass, PositionEffect, QuantityUnit
from domain.instrument_ref import InstrumentRef


# Phase 7 — `AccountSnapshot` is now the canonical
# ``domain.account.NormalizedAccountSnapshot``. The alias is kept so
# any external imports of the old name continue to work; new code
# should use the canonical class.
AccountSnapshot = NormalizedAccountSnapshot


def _client_kwargs(auth: AlpacaAuth) -> dict[str, Any]:
    return {
        "base_url": auth.base_url,
        "headers": dict(auth.headers),
        "timeout": httpx.Timeout(10.0, connect=5.0),
    }


def _get(auth: AlpacaAuth, path: str, *, client: httpx.Client | None = None) -> dict:
    if client is not None:
        r = client.get(path)
    else:
        with httpx.Client(**_client_kwargs(auth)) as c:
            r = c.get(path)
    if r.status_code >= 500:
        # Retry once on 5xx.
        if client is not None:
            r = client.get(path)
        else:
            with httpx.Client(**_client_kwargs(auth)) as c:
                r = c.get(path)
    r.raise_for_status()
    return r.json()


def get_account(
    auth: AlpacaAuth, *, client: httpx.Client | None = None
) -> NormalizedBalance:
    """GET /v2/account — cash balance + buying power."""
    data = _get(auth, "/v2/account", client=client)
    currency = Currency.USD
    cash = Decimal(str(data.get("cash", "0")))
    equity = Decimal(str(data.get("equity", "0")))
    return NormalizedBalance(
        available=CurrencyAmount(amount=cash, currency=currency),
        total=CurrencyAmount(amount=equity, currency=currency),
        used_margin=None,
        extra={
            "buying_power": data.get("buying_power"),
            "account_id": data.get("id"),
            "account_number": data.get("account_number"),
            "status": data.get("status"),
            "pattern_day_trader": data.get("pattern_day_trader"),
        },
    )


def get_positions(
    auth: AlpacaAuth, *, client: httpx.Client | None = None
) -> list[NormalizedPosition]:
    """GET /v2/positions — open positions."""
    data = _get(auth, "/v2/positions", client=client)
    out: list[NormalizedPosition] = []
    for row in data:
        qty = Decimal(str(row.get("qty", "0")))
        avg = Decimal(str(row.get("avg_entry_price", "0")))
        venue = row.get("exchange") or "XNAS"
        out.append(
            NormalizedPosition(
                instrument=InstrumentRef(
                    venue_code=venue,
                    canonical_symbol=row["symbol"],
                ),
                quantity=qty,
                quantity_unit=QuantityUnit.FRACTIONAL
                if "." in str(row.get("qty", ""))
                else QuantityUnit.WHOLE,
                average_price=avg,
                currency=Currency.USD,
                unrealized_pnl=_opt_amount(row.get("unrealized_pl"), Currency.USD),
                realized_pnl=None,
                position_effect=PositionEffect.NONE,
                asset_class=_asset_class_from_row(row),
                extra={
                    "side": row.get("side"),
                    "asset_id": row.get("asset_id"),
                    "current_price": row.get("current_price"),
                },
            )
        )
    return out


def get_account_snapshot(
    auth: AlpacaAuth, *, client: httpx.Client | None = None
) -> NormalizedAccountSnapshot:
    """One-shot helper — useful for UI and analyzer."""
    balance = get_account(auth, client=client)
    positions = get_positions(auth, client=client)
    return NormalizedAccountSnapshot(
        balance=balance,
        positions=positions,
        account_id=str(balance.extra.get("account_id", "")),
        currency=Currency.USD,
    )


def _opt_amount(raw: Any, currency: Currency) -> CurrencyAmount | None:
    if raw is None:
        return None
    try:
        return CurrencyAmount(amount=Decimal(str(raw)), currency=currency)
    except (ValueError, ArithmeticError):
        return None


def _asset_class_from_row(row: dict) -> AssetClass | None:
    cls = (row.get("asset_class") or "").lower()
    if cls == "us_equity":
        return AssetClass.EQUITY
    return None


__all__ = [
    "AccountSnapshot",
    "get_account",
    "get_account_snapshot",
    "get_positions",
]
