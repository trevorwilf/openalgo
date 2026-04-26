"""Mock Schwab-LIKE order translator.

Implements ``BrokerOrderTranslator``. ``send_native`` logs the
payload to an in-memory list (collectable by tests) and returns a
fake broker_order_id. Combo orders supported: SINGLE, OTO, OCO,
OTOCO, COMBO, MULTILEG_OPTIONS.
"""

from __future__ import annotations

import uuid
from typing import Any

from domain.account_context import AccountContext
from domain.enums import OrderType
from domain.errors import UnsupportedCapability

BROKER_CODE = "_mock_schwab_like"

# Native-shape sentinel — Schwab REST exposes "OrderStrategyType".
NATIVE_STRATEGY_TYPES = {
    "SINGLE": "SINGLE",
    "OTO": "TRIGGER",
    "OCO": "OCO",
    "OTOCO": "TRIGGER_AND_OCO",
    "COMBO": "MULTI_LEG",
    "MULTILEG_OPTIONS": "MULTI_LEG",
}

# Tests can assert on this list.
SENT_NATIVE_PAYLOADS: list[dict[str, Any]] = []


def _reset_for_tests() -> None:
    SENT_NATIVE_PAYLOADS.clear()


class MockSchwabLikeOrderTranslator:
    broker_code = BROKER_CODE

    _SUPPORTED = frozenset(
        {
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
            OrderType.STOP_LIMIT,
            OrderType.TRAILING_STOP,
        }
    )

    def validate(self, order, instrument, account_ctx: AccountContext) -> None:
        if order.order_type not in self._SUPPORTED:
            raise UnsupportedCapability(
                broker_code=BROKER_CODE,
                capability_name="order_type",
                details=f"order_type={order.order_type.value} not supported",
            )

    def to_native(
        self, order, instrument, account_ctx: AccountContext
    ) -> dict[str, Any]:
        # Schwab-style: orderStrategyType + orderLegCollection.
        return {
            "orderStrategyType": "SINGLE",
            "orderType": order.order_type.value,
            "session": order.session.value,
            "duration": order.time_in_force.value,
            "orderLegCollection": [
                {
                    "instruction": order.side.value,
                    "quantity": str(order.quantity),
                    "instrument": {
                        "venue_code": instrument.venue_code,
                        "canonical_symbol": instrument.canonical_symbol,
                        "instrument_id": str(instrument.instrument_id),
                    },
                }
            ],
            "account_hash": account_ctx.account_hash,
        }

    def to_native_combo(
        self, combo, instruments_by_leg, account_ctx: AccountContext
    ) -> dict[str, Any]:
        """Translate a NormalizedComboOrderRequest to the Schwab combo
        shape. ``instruments_by_leg`` is a list of resolved instruments,
        one per leg, in the same order.
        """
        strategy = NATIVE_STRATEGY_TYPES.get(combo.combo_type.value, "SINGLE")
        return {
            "orderStrategyType": strategy,
            "duration": combo.time_in_force.value,
            "session": combo.session.value,
            "link_id": combo.link_id,
            "orderLegCollection": [
                {
                    "instruction": leg.side.value,
                    "quantity": str(leg.quantity),
                    "orderType": leg.order_type.value,
                    "price": str(leg.price) if leg.price is not None else None,
                    "instrument": {
                        "venue_code": inst.venue_code,
                        "canonical_symbol": inst.canonical_symbol,
                        "instrument_id": str(inst.instrument_id),
                    },
                }
                for leg, inst in zip(combo.legs, instruments_by_leg)
            ],
            "account_hash": account_ctx.account_hash,
        }

    def send_native(
        self, payload: dict[str, Any], account_ctx: AccountContext | None = None
    ) -> dict[str, Any]:
        SENT_NATIVE_PAYLOADS.append(payload)
        return {
            "orderId": f"MOCK-SCHWAB-{uuid.uuid4().hex[:8]}",
            "status": "ACCEPTED",
            "native": payload,
        }

    def from_native_order_response(
        self, payload: dict[str, Any], instrument: Any
    ) -> dict[str, Any]:
        return {
            "order_id": payload.get("orderId"),
            "status": payload.get("status", "ACCEPTED"),
            "native": payload,
        }


def install_mock_schwab_like_translator() -> MockSchwabLikeOrderTranslator:
    """Install the translator into the broker_translator_registry."""
    from services.broker_translator_registry import register_broker_translator

    t = MockSchwabLikeOrderTranslator()
    register_broker_translator(t)
    _reset_for_tests()
    return t


__all__ = [
    "BROKER_CODE",
    "MockSchwabLikeOrderTranslator",
    "SENT_NATIVE_PAYLOADS",
    "install_mock_schwab_like_translator",
]
