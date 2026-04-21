"""NormalizedOrderRequest — the internal shape every order passes through.

Cross-field validators enforce the meaningful combinations:

- price required for limit-type orders (LIMIT, STOP_LIMIT, LOO, LOC)
- trigger_price required for stop-type orders (STOP, STOP_LIMIT, TRAILING_STOP)
- trailing_offset required for TRAILING_STOP
- good_till required for GTD; forbidden for non-GTD TIFs
- OPG/ATC TIFs require MOO/MOC order types respectively
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.currency import Currency
from domain.enums import (
    OrderSide,
    OrderType,
    PositionEffect,
    QuantityUnit,
    Session,
    TimeInForce,
)
from domain.instrument_ref import InstrumentRef

_LIMIT_TYPES: frozenset[OrderType] = frozenset(
    {
        OrderType.LIMIT,
        OrderType.STOP_LIMIT,
        OrderType.LIMIT_ON_OPEN,
        OrderType.LIMIT_ON_CLOSE,
    }
)

_STOP_TYPES: frozenset[OrderType] = frozenset(
    {OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP}
)


class NormalizedOrderRequest(BaseModel):
    """Broker-agnostic order request shape.

    Translated to a broker's native shape by the per-broker adapter
    layer (Phase 6+). Legacy v1 handlers translate in the other
    direction via `domain.translators`.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: InstrumentRef
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    quantity_unit: QuantityUnit
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    trailing_offset: Decimal | None = None
    time_in_force: TimeInForce
    session: Session = Session.REGULAR
    good_till: datetime | None = None
    position_effect: PositionEffect = PositionEffect.NONE
    currency: Currency | None = None
    client_order_id: str | None = None
    strategy_tag: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_cross_fields(self) -> NormalizedOrderRequest:
        # Limit-type orders require a price
        if self.order_type in _LIMIT_TYPES and self.price is None:
            raise ValueError(
                f"order_type={self.order_type.value} requires price"
            )

        # Stop-type orders require a trigger_price
        if self.order_type in _STOP_TYPES and self.trigger_price is None:
            raise ValueError(
                f"order_type={self.order_type.value} requires trigger_price"
            )

        # Trailing stop additionally requires an offset
        if self.order_type == OrderType.TRAILING_STOP and self.trailing_offset is None:
            raise ValueError("order_type=TRAILING_STOP requires trailing_offset")

        # GTD requires good_till; non-GTD must leave good_till unset
        if self.time_in_force == TimeInForce.GTD and self.good_till is None:
            raise ValueError("time_in_force=GTD requires good_till datetime")
        if self.time_in_force != TimeInForce.GTD and self.good_till is not None:
            raise ValueError(
                f"good_till only valid with time_in_force=GTD, not "
                f"{self.time_in_force.value}"
            )

        # OPG only meaningful with MARKET_ON_OPEN / LIMIT_ON_OPEN
        if self.time_in_force == TimeInForce.OPG and self.order_type not in {
            OrderType.MARKET_ON_OPEN,
            OrderType.LIMIT_ON_OPEN,
        }:
            raise ValueError(
                "time_in_force=OPG requires order_type=MARKET_ON_OPEN or LIMIT_ON_OPEN"
            )
        # ATC only meaningful with MARKET_ON_CLOSE / LIMIT_ON_CLOSE
        if self.time_in_force == TimeInForce.ATC and self.order_type not in {
            OrderType.MARKET_ON_CLOSE,
            OrderType.LIMIT_ON_CLOSE,
        }:
            raise ValueError(
                "time_in_force=ATC requires order_type=MARKET_ON_CLOSE or LIMIT_ON_CLOSE"
            )

        # Quantity must be positive
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

        return self


__all__ = ["NormalizedOrderRequest"]
