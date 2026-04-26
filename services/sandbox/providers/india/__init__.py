"""Phase 8 v4 (ADR 0026) — India sandbox provider.

Preserves the current Sandbox semantics bit-identically:

* T+1 settlement for equity and options.
* MIS / CNC / NRML products.
* INR base currency, ₹10,00,000 initial funds.
* MIS auto-square-off at the venue's regular session close
  (NSE/BSE: 15:15 IST today).
* No partial fills.

Phase 8 ships the contract conformance + the metadata. The dispatcher
into the existing ``sandbox.order_manager`` / ``sandbox.position_manager``
implementations is a focused follow-up (Phase 8-bis) — the current
``blueprints/sandbox.py`` continues to drive India sandbox behavior
directly until then.
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

REGION_CODE = "india"
_INITIAL_FUNDS = Decimal("1000000.00")
_VENUE_TZ = "Asia/Kolkata"
_MIS_SQUAREOFF_HHMM = (15, 15)


class IndiaSandboxProvider:
    region_code = REGION_CODE

    def settlement_date_for_order(
        self, order: "NormalizedOrderRequest", trade_date: date,
    ) -> date:
        return trade_date + timedelta(days=1)

    def squareoff_time_for_product(
        self, product: str, venue_code: str, on_date: date,
    ) -> datetime | None:
        if product.upper() != "MIS":
            return None
        h, m = _MIS_SQUAREOFF_HHMM
        return datetime(
            on_date.year, on_date.month, on_date.day, h, m,
            tzinfo=ZoneInfo(_VENUE_TZ),
        )

    def simulate_fill(
        self, order: "NormalizedOrderRequest", market_data: MarketDataSnapshot,
    ) -> list[Fill]:
        # India sandbox fills the full quantity at the market price
        # (last) or the limit price for limit orders. Single fill, no
        # partials. The actual implementation lives in
        # sandbox.order_manager today; this is the framework-readiness
        # contract surface.
        price = market_data.last or Decimal("0")
        qty = Decimal(str(getattr(order, "quantity", 0) or 0))
        return [Fill(quantity=qty, price=price, timestamp=market_data.timestamp or datetime.now(ZoneInfo(_VENUE_TZ)))]

    def supported_products(self) -> set[str]:
        return {"MIS", "CNC", "NRML"}

    def supported_order_types(self) -> set[str]:
        return {"MARKET", "LIMIT", "SL", "SL-M"}

    def base_currency(self) -> str:
        return "INR"

    def initial_funds(self) -> Decimal:
        return _INITIAL_FUNDS

    def partial_fills_supported(self) -> bool:
        return False

    def position_lifecycle_rules(self) -> ProviderRules:
        return ProviderRules(
            settlement_days_equity=1,
            settlement_days_options=1,
            day_trade_close_required=True,
            overnight_allowed=True,
            partial_fills_supported=False,
        )


__all__ = ["IndiaSandboxProvider", "REGION_CODE"]
