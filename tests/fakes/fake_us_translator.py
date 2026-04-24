"""Fake US :class:`BrokerOrderTranslator` used by promoted-lane tests.

This translator lives under ``tests/`` on purpose: it's not a shipping
broker, and we never want promoted code in ``broker/`` to accidentally
depend on it. The only importers should be test modules that want a
registered translator with predictable behavior.
"""

from __future__ import annotations

from typing import Any

from domain.broker_translator import AccountContext
from domain.enums import OrderType
from domain.errors import UnsupportedCapability
from services.broker_translator_registry import register_broker_translator

BROKER_CODE = "fake_us"


class FakeUSTranslator:
    """Minimal translator covering MARKET/LIMIT on XNAS/XNYS."""

    broker_code = BROKER_CODE

    def validate(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> None:
        if order.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="order_type",
                details=(
                    f"FakeUS supports MARKET/LIMIT only, got "
                    f"{order.order_type.value}"
                ),
            )

    def to_native(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        return {
            "venue": "XNAS",
            "side": order.side.value,
            "qty": str(order.quantity),
            "type": order.order_type.value,
            "price": str(order.price) if order.price is not None else None,
            "tif": order.time_in_force.value,
        }

    def send_native(
        self,
        native_payload: dict[str, Any],
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        # Deterministic in-memory response. Real broker adapters will
        # replace this hook with an HTTP call.
        return {
            "id": "fake-order-0001",
            "broker_status": "open",
            "_echo": native_payload,
        }

    def from_native_order_response(
        self,
        payload: dict[str, Any],
        instrument: Any,
    ) -> dict[str, Any]:
        if "id" not in payload:
            raise ValueError("FakeUS response missing 'id'")
        status_map = {"open": "open", "filled": "filled", "rejected": "rejected"}
        return {
            "order_id": payload["id"],
            "status": status_map.get(payload.get("broker_status", "open"), "open"),
            "native": payload,
        }


def install_fake_us_translator() -> FakeUSTranslator:
    """Register the fake translator and return the instance."""
    t = FakeUSTranslator()
    register_broker_translator(t)
    return t


__all__ = ["FakeUSTranslator", "install_fake_us_translator", "BROKER_CODE"]
