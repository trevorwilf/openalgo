"""Alpaca BrokerPositionAdapter + BrokerBalanceAdapter.

Implements the promoted-lane (`/api/v2/positions`,
`/api/v2/balances`) contracts for Alpaca by translating
``GET /v2/positions`` and ``GET /v2/account`` into the canonical
``domain.broker_market_data`` shapes.

Wired into the registry by :func:`install_alpaca_account_adapters`,
which is invoked during plugin load.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from broker.alpaca.api.auth_api import auth_handle_from_token
from domain.broker_market_data import (
    AccountContext,
    BrokerBalanceAdapter,
    BrokerPositionAdapter,
    NormalizedBalance,
    NormalizedPosition,
)


BROKER_CODE = "alpaca"


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _venue_from_alpaca(exchange: str | None, asset_class: str | None) -> str:
    """Map Alpaca's exchange field to a canonical venue code.

    Alpaca uses NASDAQ/NYSE/ARCA/BATS/AMEX/OTC. We fold to MIC codes
    so the rest of the system stays venue-symbol consistent with the
    AlpacaAdapter instrument-sync mapping.
    """
    e = (exchange or "").upper().strip()
    cls = (asset_class or "").lower().strip()
    if cls == "crypto":
        return "ALPACA_CRYPTO"
    if e in ("NASDAQ", "OTC"):
        return "XNAS"
    if e in ("NYSE", "AMEX"):
        return "XNYS"
    if e == "ARCA":
        return "ARCX"
    if e == "BATS":
        return "BATS"
    return e or "XNAS"


class AlpacaPositionAdapter:
    """Promoted-lane position adapter for Alpaca."""

    broker_code = BROKER_CODE

    def get_positions(self, account_ctx: AccountContext) -> list[NormalizedPosition]:
        token = account_ctx.get("auth_token")
        if not token:
            return []
        auth = auth_handle_from_token(token)

        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            resp = client.get("/v2/positions")

        if resp.status_code == 404 or resp.status_code == 200 and not resp.content:
            return []
        resp.raise_for_status()

        rows = resp.json() or []
        out: list[NormalizedPosition] = []
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            qty = _to_decimal(row.get("qty")) or Decimal("0")
            # Alpaca returns positive qty for both long and short; the
            # ``side`` field disambiguates. Normalize to signed quantity.
            side = (row.get("side") or "long").lower()
            if side == "short":
                qty = -qty
            out.append(
                NormalizedPosition(
                    instrument_id=row.get("asset_id") or symbol,
                    venue_code=_venue_from_alpaca(
                        row.get("exchange"), row.get("asset_class")
                    ),
                    canonical_symbol=symbol,
                    quantity=qty,
                    average_price=_to_decimal(row.get("avg_entry_price")),
                    market_value=_to_decimal(row.get("market_value")),
                    realized_pnl=None,  # Alpaca's snapshot doesn't carry this
                    unrealized_pnl=_to_decimal(row.get("unrealized_pl")),
                    currency="USD",
                    metadata={
                        "side": side,
                        "asset_class": row.get("asset_class"),
                        "current_price": row.get("current_price"),
                        "lastday_price": row.get("lastday_price"),
                    },
                )
            )
        return out


class AlpacaBalanceAdapter:
    """Promoted-lane balance adapter for Alpaca."""

    broker_code = BROKER_CODE

    def get_balance(self, account_ctx: AccountContext) -> NormalizedBalance:
        token = account_ctx.get("auth_token")
        if not token:
            return NormalizedBalance(cash=Decimal("0"), currency="USD")
        auth = auth_handle_from_token(token)

        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            resp = client.get("/v2/account")
        resp.raise_for_status()
        data = resp.json()

        cash = _to_decimal(data.get("cash")) or Decimal("0")
        equity = _to_decimal(data.get("equity"))
        buying_power = _to_decimal(data.get("buying_power"))
        # Alpaca exposes initial_margin / maintenance_margin; report
        # the larger as ``margin_used`` for a conservative figure.
        initial_margin = _to_decimal(data.get("initial_margin")) or Decimal("0")
        maintenance_margin = _to_decimal(data.get("maintenance_margin")) or Decimal("0")
        margin_used = max(initial_margin, maintenance_margin)
        if margin_used == 0:
            margin_used = None

        return NormalizedBalance(
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            margin_used=margin_used,
            currency=str(data.get("currency") or "USD"),
            metadata={
                "account_id": data.get("id"),
                "account_number": data.get("account_number"),
                "status": data.get("status"),
                "pattern_day_trader": data.get("pattern_day_trader"),
                "trading_blocked": data.get("trading_blocked"),
                "transfers_blocked": data.get("transfers_blocked"),
                "long_market_value": data.get("long_market_value"),
                "short_market_value": data.get("short_market_value"),
            },
        )


def install_alpaca_account_adapters() -> None:
    """Register Alpaca's position + balance adapters at startup."""
    from services.broker_market_data_registry import (
        register_broker_balance_adapter,
        register_broker_position_adapter,
    )

    register_broker_position_adapter(AlpacaPositionAdapter())
    register_broker_balance_adapter(AlpacaBalanceAdapter())


__all__ = [
    "BROKER_CODE",
    "AlpacaBalanceAdapter",
    "AlpacaPositionAdapter",
    "install_alpaca_account_adapters",
]
