"""Alpaca order translator + HTTP order operations.

Implements :class:`~domain.broker_translator.BrokerOrderTranslator` for
the promoted-lane ``/api/v2/orders`` dispatcher, plus the direct
HTTP helpers ``place_order``, ``get_order_status``, ``cancel_order``.

Scope (MVP): cash equities, regular session only, MARKET and LIMIT
order types, DAY and GTC time-in-force. No extended hours.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from domain.broker_translator import AccountContext
from domain.enums import OrderSide, OrderType, QuantityUnit, Session, TimeInForce
from domain.errors import UnsupportedCapability


_SUPPORTED_VENUES = {"XNAS", "XNYS", "ARCX", "BATS"}
_SUPPORTED_TYPES = {OrderType.MARKET, OrderType.LIMIT}
_SUPPORTED_TIF = {TimeInForce.DAY, TimeInForce.GTC}


class AlpacaOrderTranslator:
    broker_code = "alpaca"

    def __init__(
        self,
        auth: AlpacaAuth | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._auth = auth
        self._client = client

    # ---- BrokerOrderTranslator surface ---------------------------------

    def validate(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> None:
        if instrument is not None and instrument.venue_code not in _SUPPORTED_VENUES:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="venue",
                details=(
                    f"Alpaca does not trade venue "
                    f"{instrument.venue_code!r}"
                ),
            )
        if order.order_type not in _SUPPORTED_TYPES:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="order_type",
                details=(
                    f"Alpaca MVP supports MARKET/LIMIT only, got "
                    f"{order.order_type.value}"
                ),
            )
        if order.time_in_force not in _SUPPORTED_TIF:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="time_in_force",
                details=(
                    f"Alpaca MVP supports DAY/GTC only, got "
                    f"{order.time_in_force.value}"
                ),
            )
        if order.session != Session.REGULAR:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="session",
                details=(
                    f"Alpaca MVP is regular-session only, got "
                    f"{order.session.value}"
                ),
            )
        if order.quantity_unit == QuantityUnit.LOTS:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="quantity_unit",
                details="Alpaca does not support LOTS",
            )

    def to_native(
        self,
        order: Any,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        symbol = (
            instrument.broker_native_symbol
            if (instrument is not None and instrument.broker_native_symbol)
            else (
                instrument.canonical_symbol
                if instrument is not None
                else (order.instrument.canonical_symbol or "")
            )
        )
        side = "buy" if order.side == OrderSide.BUY else "sell"
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "market" if order.order_type == OrderType.MARKET else "limit",
            "time_in_force": (
                "day" if order.time_in_force == TimeInForce.DAY else "gtc"
            ),
        }
        if order.quantity_unit == QuantityUnit.NOTIONAL:
            body["notional"] = str(order.quantity)
        else:
            body["qty"] = str(order.quantity)

        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise UnsupportedCapability(
                    broker_code=self.broker_code,
                    capability_name="limit_price",
                    details="LIMIT order requires a price",
                )
            body["limit_price"] = str(order.price)

        if order.client_order_id:
            body["client_order_id"] = order.client_order_id

        return body

    def send_native(
        self,
        native_payload: dict[str, Any],
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Dispatcher hook — POST the native payload to Alpaca."""
        return self._post("/v2/orders", native_payload)

    def from_native_order_response(
        self,
        payload: dict[str, Any],
        instrument: Any,
    ) -> dict[str, Any]:
        if "id" not in payload:
            raise ValueError("Alpaca order response missing `id`")
        return {
            "order_id": payload["id"],
            "status": payload.get("status", "new"),
            "filled_quantity": _opt_decimal(payload.get("filled_qty")),
            "filled_avg_price": _opt_decimal(payload.get("filled_avg_price")),
            "native": payload,
        }

    # ---- Direct helpers (used by Phase 7 / ops tools) ------------------

    def place_order(
        self, payload: dict[str, Any], account_ctx: AccountContext | None = None
    ) -> dict[str, Any]:
        return self._post("/v2/orders", payload)

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        return self._get(f"/v2/orders/{order_id}")

    def cancel_order(self, order_id: str) -> None:
        self._delete(f"/v2/orders/{order_id}")

    # ---- HTTP plumbing -------------------------------------------------

    def _resolve_auth(self) -> AlpacaAuth:
        if self._auth is None:
            return authenticate()
        return self._auth

    def _client_kwargs(self, auth: AlpacaAuth) -> dict[str, Any]:
        return {
            "base_url": auth.base_url,
            "headers": dict(auth.headers),
            "timeout": httpx.Timeout(10.0, connect=5.0),
        }

    def _post(self, path: str, body: dict) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.post(path, json=body)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.get(path)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.get(path)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.delete(path)
        else:
            with httpx.Client(**self._client_kwargs(auth)) as c:
                r = c.delete(path)
        if r.status_code not in (200, 204):
            r.raise_for_status()


def _opt_decimal(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        return str(Decimal(str(raw)))
    except (ArithmeticError, ValueError):
        return None


__all__ = ["AlpacaOrderTranslator"]
