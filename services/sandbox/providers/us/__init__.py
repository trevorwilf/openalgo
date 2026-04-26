"""Phase 8 v4 (ADR 0026) — US sandbox provider (mock data).

US sandbox semantics:

* T+2 settlement for equities, T+1 for options.
* DAY_TRADE / OVERNIGHT / MARGIN products (no MIS concept).
* USD base currency, $100,000 initial mock funds.
* DAY_TRADE auto-close at the venue's regular session close
  (XNYS / XNAS: 16:00 ET).
* Basic partial fill simulation: a market order at low liquidity
  may fill in 2 chunks (mock).
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

REGION_CODE = "us"
_INITIAL_FUNDS = Decimal("100000.00")
_VENUE_TZ = "America/New_York"
_DAY_TRADE_CLOSE_HHMM = (16, 0)
_LOW_LIQUIDITY_VOLUME_THRESHOLD = Decimal("100")


def _is_option_order(order: "NormalizedOrderRequest") -> bool:
    asset_class = getattr(order, "asset_class", None)
    if asset_class is None:
        return False
    val = getattr(asset_class, "value", str(asset_class))
    return str(val).upper() == "OPTION"


class USSandboxProvider:
    region_code = REGION_CODE

    def settlement_date_for_order(
        self, order: "NormalizedOrderRequest", trade_date: date,
    ) -> date:
        days = 1 if _is_option_order(order) else 2
        # Skip weekends (mock-friendly business-day approximation).
        d = trade_date
        while days > 0:
            d = d + timedelta(days=1)
            if d.weekday() < 5:  # 0..4 = Mon..Fri
                days -= 1
        return d

    def squareoff_time_for_product(
        self, product: str, venue_code: str, on_date: date,
    ) -> datetime | None:
        if product.upper() != "DAY_TRADE":
            return None
        h, m = _DAY_TRADE_CLOSE_HHMM
        return datetime(
            on_date.year, on_date.month, on_date.day, h, m,
            tzinfo=ZoneInfo(_VENUE_TZ),
        )

    def simulate_fill(
        self, order: "NormalizedOrderRequest", market_data: MarketDataSnapshot,
    ) -> list[Fill]:
        price = market_data.last or market_data.ask or Decimal("0")
        qty = Decimal(str(getattr(order, "quantity", 0) or 0))
        ts = market_data.timestamp or datetime.now(ZoneInfo(_VENUE_TZ))

        # Partial-fill simulation: if market data reports low
        # liquidity (volume < threshold) and the order is for more
        # than half of that volume, split into two fills.
        if (
            market_data.volume is not None
            and market_data.volume < _LOW_LIQUIDITY_VOLUME_THRESHOLD
            and qty > market_data.volume / 2
        ):
            first_qty = qty / 2
            second_qty = qty - first_qty
            return [
                Fill(quantity=first_qty, price=price, timestamp=ts),
                Fill(
                    quantity=second_qty,
                    price=price,
                    timestamp=ts + timedelta(seconds=5),
                ),
            ]
        return [Fill(quantity=qty, price=price, timestamp=ts)]

    def supported_products(self) -> set[str]:
        return {"DAY_TRADE", "OVERNIGHT", "MARGIN"}

    def supported_order_types(self) -> set[str]:
        return {"MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAILING_STOP"}

    def base_currency(self) -> str:
        return "USD"

    def initial_funds(self) -> Decimal:
        return _INITIAL_FUNDS

    def partial_fills_supported(self) -> bool:
        return True

    def position_lifecycle_rules(self) -> ProviderRules:
        return ProviderRules(
            settlement_days_equity=2,
            settlement_days_options=1,
            day_trade_close_required=True,
            overnight_allowed=True,
            partial_fills_supported=True,
        )


__all__ = ["REGION_CODE", "USSandboxProvider"]
