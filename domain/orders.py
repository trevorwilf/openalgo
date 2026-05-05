"""NormalizedOrderRequest — the internal shape every order passes through.

Cross-field validators enforce the meaningful combinations:

- price required for limit-type orders (LIMIT, STOP_LIMIT, LOO, LOC)
- trigger_price required for stop-type orders (STOP, STOP_LIMIT)
  TRAILING_STOP is NOT in this set — its trigger is computed
  dynamically by the broker from ``trailing_offset``.
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

# Order types that require an explicit ``trigger_price``. Note:
# TRAILING_STOP is INTENTIONALLY excluded — at every supported broker
# (Alpaca, Schwab, Webull, IBKR, Zerodha…) a trailing stop's trigger
# is computed dynamically by the broker from ``trailing_offset``
# (dollars or percent of high-water mark). Including it here used to
# block every TRAILING_STOP placement at /api/v2/orders with
# ``order_type=TRAILING_STOP requires trigger_price`` despite the
# normalized field that actually carries the stop semantics
# (``trailing_offset``) being correctly populated.
_STOP_TYPES: frozenset[OrderType] = frozenset(
    {OrderType.STOP, OrderType.STOP_LIMIT}
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
    # Promoted-lane brokers (Alpaca, IBKR, Schwab, Webull, …) gate
    # extended-session execution on a single boolean rather than a
    # session enum because the underlying broker API uses one. We
    # expose it as a typed top-level field so consumers don't have to
    # smuggle it through ``extra`` (which would lose schema discovery
    # at the v2 swagger layer). Defaults False — order routes only
    # through the regular session unless the operator opts in.
    extended_hours: bool = False
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


class OrderLeg(BaseModel):
    """One leg of a multi-leg / combo order.

    Phase 8: see ``NormalizedComboOrderRequest``. Each leg is a
    self-contained instruction; combo-level fields (``time_in_force``,
    ``session``) live on the parent request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_ref: InstrumentRef
    side: OrderSide
    quantity: Decimal
    quantity_unit: QuantityUnit
    order_type: OrderType
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    position_effect: PositionEffect | None = None

    @model_validator(mode="after")
    def _validate(self) -> "OrderLeg":
        if self.order_type in _LIMIT_TYPES and self.price is None:
            raise ValueError(
                f"OrderLeg order_type={self.order_type.value} requires price"
            )
        if self.order_type in _STOP_TYPES and self.trigger_price is None:
            raise ValueError(
                f"OrderLeg order_type={self.order_type.value} requires trigger_price"
            )
        if self.quantity <= 0:
            raise ValueError("OrderLeg quantity must be positive")
        return self


class NormalizedComboOrderRequest(BaseModel):
    """Multi-leg / linked-order request.

    Phase 8 — supports Schwab OrderStrategyType (OTO/OCO/OTOCO/COMBO),
    Webull combo orders, and US-retail bracket orders. Single-leg
    orders MAY be expressed here with ``combo_type=SINGLE`` and one
    leg; the existing ``NormalizedOrderRequest`` remains the canonical
    single-order shape for backward compatibility.

    Translators opt in to combo support via the new
    ``BrokerCapabilities.products[*].supports_combo_types`` capability
    list. No existing translator is forced to handle combos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    combo_type: "ComboType"
    time_in_force: TimeInForce
    session: Session
    legs: list[OrderLeg] = Field(default_factory=list)
    link_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> "NormalizedComboOrderRequest":
        if not self.legs:
            raise ValueError("NormalizedComboOrderRequest requires at least one leg")
        # SINGLE combo must have exactly one leg.
        from domain.enums import ComboType as _CT

        if self.combo_type == _CT.SINGLE and len(self.legs) != 1:
            raise ValueError("combo_type=SINGLE requires exactly one leg")
        # OCO / OTO / OTOCO must have at least two legs.
        if self.combo_type in {_CT.OCO, _CT.OTO, _CT.OTOCO} and len(self.legs) < 2:
            raise ValueError(
                f"combo_type={self.combo_type.value} requires at least 2 legs"
            )
        # BRACKET is parent + take-profit + stop — exactly three legs.
        if self.combo_type == _CT.BRACKET and len(self.legs) != 3:
            raise ValueError("combo_type=BRACKET requires exactly 3 legs")
        return self


# Forward-resolve the ComboType reference used in the model field.
from domain.enums import ComboType  # noqa: E402

NormalizedComboOrderRequest.model_rebuild()


__all__ = [
    "NormalizedComboOrderRequest",
    "NormalizedOrderRequest",
    "OrderLeg",
]
