"""Phase 9-bis-physical (T-23 Group A) — re-export shim.

The actual definitions live in
``market_regions.india.legacy_v1.restx_api.account_schema`` after the
physical relocation. This module re-exports every name so existing
``from restx_api.account_schema import FundsSchema`` (etc.) imports
continue working without per-callsite changes.

Future engagements may incrementally migrate importers to the new
path and ultimately drop this shim.
"""

from __future__ import annotations

from market_regions.india.legacy_v1.restx_api.account_schema import (  # noqa: F401
    AnalyzerSchema,
    AnalyzerToggleSchema,
    ChartSchema,
    FundsSchema,
    HoldingsSchema,
    OpenPositionSchema,
    OrderbookSchema,
    OrderStatusSchema,
    PingSchema,
    PnlSymbolsSchema,
    PositionbookSchema,
    TradebookSchema,
)

__all__ = [
    "AnalyzerSchema",
    "AnalyzerToggleSchema",
    "ChartSchema",
    "FundsSchema",
    "HoldingsSchema",
    "OpenPositionSchema",
    "OrderbookSchema",
    "OrderStatusSchema",
    "PingSchema",
    "PnlSymbolsSchema",
    "PositionbookSchema",
    "TradebookSchema",
]
