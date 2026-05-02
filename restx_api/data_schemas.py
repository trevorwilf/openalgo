"""Phase 9-bis-physical (T-23 Group A) — re-export shim.

The actual definitions live in
``market_regions.india.legacy_v1.restx_api.data_schemas`` after the
physical relocation. This module re-exports every name so existing
``from restx_api.data_schemas import QuotesSchema`` (etc.) imports
continue working without per-callsite changes.

Future engagements may incrementally migrate importers to the new
path and ultimately drop this shim.
"""

from __future__ import annotations

from market_regions.india.legacy_v1.restx_api.data_schemas import (  # noqa: F401
    LEGACY_INDIA_COMPATIBILITY,
    DepthSchema,
    ExpirySchema,
    HistorySchema,
    InstrumentsSchema,
    IntervalsSchema,
    MarketHolidaysSchema,
    MarketTimingsSchema,
    MultiOptionGreeksSchema,
    MultiQuotesSchema,
    OptionChainSchema,
    OptionGreeksSchema,
    OptionSymbolRequest,
    OptionSymbolSchema,
    QuotesSchema,
    SearchSchema,
    SymbolExchangePair,
    SymbolSchema,
    TickerSchema,
)

__all__ = [
    "DepthSchema",
    "ExpirySchema",
    "HistorySchema",
    "InstrumentsSchema",
    "IntervalsSchema",
    "MarketHolidaysSchema",
    "MarketTimingsSchema",
    "MultiOptionGreeksSchema",
    "MultiQuotesSchema",
    "OptionChainSchema",
    "OptionGreeksSchema",
    "OptionSymbolRequest",
    "OptionSymbolSchema",
    "QuotesSchema",
    "SearchSchema",
    "SymbolExchangePair",
    "SymbolSchema",
    "TickerSchema",
]
