"""BrokerOrderRule — declarative per-broker order constraints.

A Pydantic mirror of :class:`database.broker_rules_repo.BrokerOrderRulesRow`.
Rows are loaded from the DB, wrapped into this model for validation,
and consumed by :mod:`services.rule_enforcement`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.enums import AssetClass, OrderSide, OrderType, QuantityUnit, Session, TimeInForce


class BrokerOrderRule(BaseModel):
    """Declarative rule describing what a broker allows.

    Rules with more non-null qualifier fields are considered more
    specific. The rule-enforcement service picks the most specific rule
    that matches the order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_code: str
    venue_code: str | None = None
    asset_class: AssetClass | None = None
    session: Session | None = None
    side: OrderSide | None = None
    quantity_unit: QuantityUnit | None = None
    allowed_order_types: list[OrderType]
    allowed_time_in_force: list[TimeInForce]
    requires_limit_price: bool = False
    allows_fractional: bool = False
    allows_notional: bool = False
    allows_short: bool = False
    metadata: dict[str, Any] = {}

    @property
    def specificity(self) -> int:
        """Number of non-null qualifier fields. Ties are broken by the
        caller's preferred order (more specific first)."""
        return sum(
            1
            for v in (
                self.venue_code,
                self.asset_class,
                self.session,
                self.side,
                self.quantity_unit,
            )
            if v is not None
        )


__all__ = ["BrokerOrderRule"]
