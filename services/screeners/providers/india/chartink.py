"""Phase 10 v4 (ADR 0028) — Chartink India screener provider.

Parses Chartink's webhook payload format and maps signals into
NormalizedOrderRequest objects for India brokers.

Chartink webhook payload shape (representative):

    {
        "stocks": "SBIN,RELIANCE,TCS",
        "trigger_prices": "525.5,2840.0,3500.0",
        "triggered_at": "2:34 pm",
        "scan_name": "Bullish Pattern",
        "alert_name": "Bullish Pattern Alert",
        "webhook_url": "..."
    }

The provider handles the comma-separated stocks/prices, normalizes
the trigger time, and produces one order per symbol via the user's
``ScreenerConfig`` (quantity / product / venue).

This provider is the India-shaped reference. The
``blueprints/chartink.py`` blueprint continues to drive the existing
Chartink flow directly today (parity-protected); Phase 10-bis wires
the blueprint to dispatch through this provider.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from services.screeners.providers.base import (
    ScreenerConfig,
    ScreenerSignal,
)

if TYPE_CHECKING:  # pragma: no cover
    from domain.orders import NormalizedOrderRequest

PROVIDER_CODE = "chartink"
REGION_CODE = "india"
SUPPORTED_VENUES = ["NSE", "BSE"]


class ChartinkScreenerProvider:
    provider_code = PROVIDER_CODE
    region_code = REGION_CODE
    supported_venues = list(SUPPORTED_VENUES)

    def validate_webhook_payload(self, payload: dict) -> ScreenerSignal:
        if not isinstance(payload, dict):
            raise ValueError("Chartink payload must be a dict")
        stocks_raw = payload.get("stocks")
        if not stocks_raw:
            raise ValueError("Chartink payload missing 'stocks'")
        symbols = [s.strip().upper() for s in str(stocks_raw).split(",") if s.strip()]
        if not symbols:
            raise ValueError("Chartink payload 'stocks' yielded no symbols")
        prices_raw = payload.get("trigger_prices")
        price: Decimal | None = None
        if prices_raw:
            first = str(prices_raw).split(",")[0].strip()
            if first:
                try:
                    price = Decimal(first)
                except Exception:
                    price = None
        signal_type = self._infer_signal_type(payload)
        # Chartink's "triggered_at" is e.g. "2:34 pm"; we keep the
        # raw payload but don't try to parse the time here (operator
        # may not have set tz on the message). Future Phase 10-bis
        # could resolve via venue tz.
        return ScreenerSignal(
            signal_type=signal_type,
            symbols=symbols,
            price=price,
            timestamp=datetime.utcnow(),
            raw_payload=dict(payload),
            metadata={
                "scan_name": payload.get("scan_name"),
                "alert_name": payload.get("alert_name"),
                "triggered_at_raw": payload.get("triggered_at"),
            },
        )

    def _infer_signal_type(self, payload: dict) -> str:
        scan_name = str(payload.get("scan_name") or "").lower()
        alert_name = str(payload.get("alert_name") or "").lower()
        text = f"{scan_name} {alert_name}"
        if "exit" in text or "square off" in text:
            return "exit"
        if "sell" in text or "bearish" in text or "short" in text:
            return "sell"
        return "buy"

    def supported_signal_types(self) -> set[str]:
        return {"buy", "sell", "exit"}

    def map_signal_to_orders(
        self, signal: ScreenerSignal, config: ScreenerConfig,
    ) -> list["NormalizedOrderRequest"]:
        # Lazy import to avoid pydantic-heavy import at module load.
        from domain.enums import OrderSide, OrderType, QuantityUnit, TimeInForce
        from domain.instrument_ref import InstrumentRef
        from domain.orders import NormalizedOrderRequest

        side_map = {
            "buy": OrderSide.BUY,
            "sell": OrderSide.SELL,
            "exit": OrderSide.SELL,
        }
        side = side_map[signal.signal_type]
        order_type_value = config.order_type.upper()
        try:
            order_type = OrderType(order_type_value)
        except ValueError:
            order_type = OrderType.MARKET
        venue = config.venue_code or self.supported_venues[0]

        # The product type is broker-translator side, not an enum on
        # NormalizedOrderRequest. Store it in `extra` so the broker
        # translator can map it (legacy India translators read
        # `extra["product"]`).
        out: list[NormalizedOrderRequest] = []
        for symbol in signal.symbols:
            order = NormalizedOrderRequest(
                instrument=InstrumentRef(
                    venue_code=venue,
                    canonical_symbol=symbol,
                ),
                side=side,
                order_type=order_type,
                quantity=Decimal(str(config.quantity)),
                quantity_unit=QuantityUnit.WHOLE,
                time_in_force=TimeInForce.DAY,
                price=signal.price if order_type != OrderType.MARKET else None,
                extra={
                    "product": config.product.upper(),
                    "screener_provider": self.provider_code,
                    "scan_name": signal.metadata.get("scan_name"),
                },
            )
            out.append(order)
        return out


__all__ = ["ChartinkScreenerProvider", "PROVIDER_CODE", "REGION_CODE"]
