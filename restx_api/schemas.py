"""Phase 9-bis-physical (T-23 Group A) — re-export shim.

The actual definitions live in
``market_regions.india.legacy_v1.restx_api.schemas`` after the
physical relocation. This module re-exports every name so existing
``from restx_api.schemas import OrderSchema`` (etc.) imports continue
working without per-callsite changes.

Future engagements may incrementally migrate importers to the new
path and ultimately drop this shim.
"""

from __future__ import annotations

from market_regions.india.legacy_v1.restx_api.schemas import (  # noqa: F401
    BasketOrderItemSchema,
    BasketOrderSchema,
    CancelAllOrderSchema,
    CancelOrderSchema,
    ClosePositionSchema,
    MarginCalculatorSchema,
    MarginPositionSchema,
    ModifyOrderSchema,
    OptionsMultiOrderLegSchema,
    OptionsMultiOrderSchema,
    OptionsOrderSchema,
    OrderSchema,
    SmartOrderSchema,
    SplitOrderSchema,
    SyntheticFutureSchema,
)

__all__ = [
    "BasketOrderItemSchema",
    "BasketOrderSchema",
    "CancelAllOrderSchema",
    "CancelOrderSchema",
    "ClosePositionSchema",
    "MarginCalculatorSchema",
    "MarginPositionSchema",
    "ModifyOrderSchema",
    "OptionsMultiOrderLegSchema",
    "OptionsMultiOrderSchema",
    "OptionsOrderSchema",
    "OrderSchema",
    "SmartOrderSchema",
    "SplitOrderSchema",
    "SyntheticFutureSchema",
]
