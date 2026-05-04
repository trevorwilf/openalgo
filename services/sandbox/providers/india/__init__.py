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


def _resolve_initial_funds_from_region_plugin() -> Decimal:
    """T-16 (v7 Phase 4-bis-3): read sandbox initial funds from the
    India region plugin's metadata instead of hard-coding ₹10L in
    Python source.

    Resolution chain:
    1. ``market_regions/india/plugin.json::metadata.sandbox_initial_funds``
       (the canonical source of truth post-T-16).
    2. Fallback to ``Decimal("1000000.00")`` (₹10L) when the region
       plugin isn't loaded yet — matches the legacy provider value
       so India parity baselines stay bit-identical.
    """
    try:
        from utils.region_loader import get_market_region, load_market_regions

        region = get_market_region("india")
        if region is None:
            load_market_regions()
            region = get_market_region("india")
        if region is not None:
            metadata = getattr(region, "metadata", None) or {}
            value = metadata.get("sandbox_initial_funds")
            if value:
                return Decimal(str(value))
    except Exception:
        pass
    return Decimal("1000000.00")


# Phase 8 v4 (ADR 0026) framework-readiness contract value: ₹10L.
# Sourced from ``market_regions/india/plugin.json`` post-T-16.
# Bit-identical to the legacy hard-coded value so
# ``tests/parity/baseline/parity_sandbox_india`` stays pinned.
_INITIAL_FUNDS = _resolve_initial_funds_from_region_plugin()
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

    # Phase 2-bis-3 (T-13 wiring) — expose the legacy India sandbox
    # engine classes as a compose-able dict so consumers
    # (services/sandbox_service.py, blueprints/sandbox.py) can
    # eventually route through the dispatcher rather than
    # importing from ``sandbox.*`` directly. The classes themselves
    # remain unchanged — this provider does NOT duplicate their
    # behavior; it just makes them reachable via
    # ``get_sandbox_provider("india").manager_classes()``.
    def manager_classes(self) -> dict[str, type]:
        """Return the legacy India sandbox manager classes by role.

        Keys: ``order``, ``position``, ``fund``, ``holdings``,
        ``squareoff``, ``execution``, ``catch_up``. Values are the
        actual class objects from the ``sandbox.*`` package; callers
        ``cls(user_id=...)`` etc. as before, but discover them
        through the provider rather than module-level imports.

        India parity: the values are exactly the classes
        ``services/sandbox_service.py`` and
        ``services/analyzer_service.py`` import today; the dispatcher
        route is additive — the legacy direct-import call sites still
        work bit-identically. ``services/sandbox_service.py`` is the
        consumer migrated in v9-bis-2.
        """
        from sandbox.fund_manager import FundManager
        from sandbox.holdings_manager import HoldingsManager
        from sandbox.order_manager import OrderManager
        from sandbox.position_manager import PositionManager
        from sandbox.squareoff_manager import SquareOffManager

        return {
            "order": OrderManager,
            "position": PositionManager,
            "fund": FundManager,
            "holdings": HoldingsManager,
            "squareoff": SquareOffManager,
        }

    # Phase 2-bis-3-3 (T-13 / T-14 remaining) — expose the legacy
    # India sandbox thread/control modules so consumers
    # (``services/analyzer_service.py``, ``services/sandbox_service.py``)
    # can dispatch through ``get_sandbox_provider("india").service_modules()``
    # rather than importing ``sandbox.execution_thread`` /
    # ``sandbox.squareoff_thread`` / ``sandbox.position_manager``
    # directly.
    def service_modules(self) -> dict[str, object]:
        """Return the legacy India sandbox thread/control modules by role.

        Keys: ``execution_thread``, ``squareoff_thread``,
        ``position_manager``. Values are module objects; callers use
        them as before (``mod.start_execution_engine()`` etc.).
        """
        from sandbox import execution_thread, position_manager, squareoff_thread

        return {
            "execution_thread": execution_thread,
            "squareoff_thread": squareoff_thread,
            "position_manager": position_manager,
        }


__all__ = ["IndiaSandboxProvider", "REGION_CODE"]
