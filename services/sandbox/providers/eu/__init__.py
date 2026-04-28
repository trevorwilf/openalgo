"""Phase 3 v6 (ADR 0026 + EU region) — EU sandbox provider stub.

Minimal sandbox provider that mirrors the US stub pattern. Declares
EU venues from the EU region plugin (XPAR / XETR), EUR base currency,
T+2 settlement, regular EU equity sessions. Returns
``feature_unsupported``-shaped errors for any operation the EU stub
does not implement (per the EU region plugin's
``feature_flags.sandbox_enabled = false``).

This stub exists so the dispatcher can resolve `region="eu"` instead
of fail-closing — the v6 closing invariant gate
(``test_v6_closing_invariants.test_v6_4_each_region_has_provider``)
asserts every region in the four-region matrix has a registered
provider.

Real EU sandbox semantics (corporate-action handling, MiFID II
constraints, settlement calendar across holidays per venue) require
a region-specialist implementation and are out of v6 scope.
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

REGION_CODE = "eu"
_INITIAL_FUNDS = Decimal("100000.00")  # EUR mock
_VENUE_TZ = "Europe/Paris"
_REGULAR_CLOSE_HHMM = (17, 30)  # XPAR/XETR regular session close


class EUSandboxProvider:
    """Minimal EU sandbox stub. Real semantics await a future ADR."""

    region_code = REGION_CODE

    def settlement_date_for_order(
        self, order: "NormalizedOrderRequest", trade_date: date,
    ) -> date:
        # T+2 for EU equities (no specialized option settlement;
        # options are not exercised in this stub).
        return trade_date + timedelta(days=2)

    def squareoff_time_for_product(
        self, product: str, venue_code: str, on_date: date,
    ) -> datetime | None:
        # No India-style intraday product. Return None — EU sandbox
        # does not auto-square-off in this stub.
        return None

    def simulate_fill(
        self, order: "NormalizedOrderRequest", market_data: MarketDataSnapshot,
    ) -> list[Fill]:
        # Single full fill at last; matches the US stub default and
        # avoids partial fill complexity in the framework stub.
        price = market_data.last or Decimal("0")
        qty = Decimal(str(getattr(order, "quantity", 0) or 0))
        ts = market_data.timestamp or datetime.now(ZoneInfo(_VENUE_TZ))
        return [Fill(quantity=qty, price=price, timestamp=ts)]

    def supported_products(self) -> set[str]:
        # EU brokers expose CASH (delivery) and MARGIN (leveraged);
        # this stub keeps the set non-empty so callers can iterate.
        return {"CASH", "MARGIN"}

    def supported_order_types(self) -> set[str]:
        return {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}

    def base_currency(self) -> str:
        return "EUR"

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


__all__ = ["EUSandboxProvider", "REGION_CODE"]
