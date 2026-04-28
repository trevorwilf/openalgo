"""Phase 3 v6 (ADR 0026 + UK region) — UK sandbox provider stub.

Minimal sandbox provider mirroring the EU stub pattern. Declares the
LSE venue (XLON), GBP base currency, T+2 settlement, LSE regular
session 08:00-16:30 London time. Real UK sandbox semantics are out
of v6 scope.

Stub exists so the dispatcher resolves ``region="uk"`` instead of
fail-closing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from services.sandbox.providers.base import (
    Fill,
    MarketDataSnapshot,
    ProviderRules,
)

if TYPE_CHECKING:  # pragma: no cover
    from domain.orders import NormalizedOrderRequest

REGION_CODE = "uk"
_INITIAL_FUNDS = Decimal("100000.00")  # GBP mock
_VENUE_TZ = "Europe/London"


class UKSandboxProvider:
    """Minimal UK sandbox stub. Real semantics await a future ADR."""

    region_code = REGION_CODE

    def settlement_date_for_order(
        self, order: "NormalizedOrderRequest", trade_date: date,
    ) -> date:
        return trade_date + timedelta(days=2)

    def squareoff_time_for_product(
        self, product: str, venue_code: str, on_date: date,
    ) -> datetime | None:
        return None

    def simulate_fill(
        self, order: "NormalizedOrderRequest", market_data: MarketDataSnapshot,
    ) -> list[Fill]:
        price = market_data.last or Decimal("0")
        qty = Decimal(str(getattr(order, "quantity", 0) or 0))
        ts = market_data.timestamp or datetime.now(ZoneInfo(_VENUE_TZ))
        return [Fill(quantity=qty, price=price, timestamp=ts)]

    def supported_products(self) -> set[str]:
        return {"CASH", "MARGIN"}

    def supported_order_types(self) -> set[str]:
        return {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}

    def base_currency(self) -> str:
        return "GBP"

    def initial_funds(self) -> Decimal:
        return _INITIAL_FUNDS

    def partial_fills_supported(self) -> bool:
        return False

    def position_lifecycle_rules(self) -> ProviderRules:
        return ProviderRules(
            settlement_days_equity=2,
            settlement_days_options=1,
            day_trade_close_required=False,
            overnight_allowed=True,
            partial_fills_supported=False,
        )


__all__ = ["REGION_CODE", "UKSandboxProvider"]
