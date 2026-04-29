"""Mock Webull-LIKE order translator.

Implements ``BrokerOrderTranslator``. Combo support: SINGLE, OCO, OTO,
OTOCO. Webull-native shape uses combo_type + entrust_type + orderType.
"""

from __future__ import annotations

import uuid
from typing import Any

from domain.account_context import AccountContext
from domain.enums import OrderType
from domain.errors import UnsupportedCapability

BROKER_CODE = "_mock_webull_like"

NATIVE_ENTRUST_TYPES = {
    "SINGLE": "NORMAL",
    "OCO": "OCO",
    "OTO": "STOP_TRAIL",
    "OTOCO": "BRACKET",
    # v6 Phase 4-bis — MULTILEG_OPTIONS extension. Webull's
    # multi-leg options API uses "MULTILEG_OPTIONS" directly.
    "MULTILEG_OPTIONS": "MULTILEG_OPTIONS",
}

# v6 Phase 4-bis — alias as NATIVE_STRATEGY_TYPES for symmetry with
# the mock Schwab translator's name; contract tests reference both.
NATIVE_STRATEGY_TYPES = NATIVE_ENTRUST_TYPES

SENT_NATIVE_PAYLOADS: list[dict[str, Any]] = []


def _reset_for_tests() -> None:
    SENT_NATIVE_PAYLOADS.clear()


class MockWebullLikeOrderTranslator:
    broker_code = BROKER_CODE

    _SUPPORTED = frozenset(
        {
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
            OrderType.STOP_LIMIT,
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
        # Webull-style: combo_type + entrust_type + orderType.
        return {
            "combo_type": "NORMAL",
            "entrust_type": "NORMAL",
            "orderType": order.order_type.value,
            "side": order.side.value,
            "quantity": str(order.quantity),
            "tif": order.time_in_force.value,
            "session": order.session.value,
            "instrument": {
                "venue_code": instrument.venue_code,
                "canonical_symbol": instrument.canonical_symbol,
                "instrument_id": str(instrument.instrument_id),
            },
            "subaccount_id": account_ctx.subaccount_id,
        }

    def to_native_combo(
        self, combo, instruments_by_leg, account_ctx: AccountContext
    ) -> dict[str, Any]:
        return {
            "combo_type": NATIVE_ENTRUST_TYPES.get(combo.combo_type.value, "NORMAL"),
            "entrust_type": NATIVE_ENTRUST_TYPES.get(combo.combo_type.value, "NORMAL"),
            "tif": combo.time_in_force.value,
            "session": combo.session.value,
            "link_id": combo.link_id,
            "orders": [
                {
                    "side": leg.side.value,
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
            "subaccount_id": account_ctx.subaccount_id,
        }

    def send_native(
        self, payload: dict[str, Any], account_ctx: AccountContext | None = None
    ) -> dict[str, Any]:
        SENT_NATIVE_PAYLOADS.append(payload)
        return {
            "orderId": f"MOCK-WEBULL-{uuid.uuid4().hex[:8]}",
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


def install_mock_webull_like_translator() -> MockWebullLikeOrderTranslator:
    from services.broker_translator_registry import register_broker_translator

    t = MockWebullLikeOrderTranslator()
    register_broker_translator(t)
    _reset_for_tests()
    return t


__all__ = [
    "BROKER_CODE",
    "MockWebullLikeOrderTranslator",
    "SENT_NATIVE_PAYLOADS",
    "install_mock_webull_like_translator",
]
