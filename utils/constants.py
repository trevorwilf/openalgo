"""Phase 9-bis-physical (T-23 Group B) — re-export shim.

The actual constants live in ``market_regions.india.legacy_v1.constants``
after the physical relocation. This module re-exports every public
name so existing ``from utils.constants import VALID_EXCHANGES``
(etc.) imports continue working without per-callsite changes.

NEW CODE MUST NOT IMPORT ``VALID_EXCHANGES``, ``VALID_PRODUCT_TYPES``,
or ``VALID_PRICE_TYPES`` from this module. New non-India request
validation lives in ``domain/orders.py`` and the v2 endpoints under
``restx_api/v2/``. ADR 0017 formalizes the legacy stamp;
``tests/contracts/test_v1_schemas_classification.py`` enforces the
import block on classified PROMOTED_CORE files.

Future engagements may incrementally migrate importers to the new
path and ultimately drop this shim.

Reference: https://docs.openalgo.in/api-documentation/v1/order-constants
"""

from __future__ import annotations

from market_regions.india.legacy_v1.constants import (  # noqa: F401
    ACTION_BUY,
    ACTION_SELL,
    CRYPTO_BROKERS,
    CRYPTO_EXCHANGES,
    CRYPTO_QUOTE_CURRENCY,
    DEFAULT_DISCLOSED_QUANTITY,
    DEFAULT_PRICE,
    DEFAULT_PRICE_TYPE,
    DEFAULT_PRODUCT_TYPE,
    DEFAULT_TRIGGER_PRICE,
    EXCHANGE_BADGE_COLORS,
    EXCHANGE_BCD,
    EXCHANGE_BFO,
    EXCHANGE_BSE,
    EXCHANGE_BSE_INDEX,
    EXCHANGE_CDS,
    EXCHANGE_CRYPTO,
    EXCHANGE_MCX,
    EXCHANGE_NCDEX,
    EXCHANGE_NFO,
    EXCHANGE_NSE,
    EXCHANGE_NSE_INDEX,
    FNO_EXCHANGES,
    INSTRUMENT_PERPFUT,
    LEGACY_INDIA_COMPATIBILITY,
    PRICE_TYPE_LIMIT,
    PRICE_TYPE_MARKET,
    PRICE_TYPE_SL,
    PRICE_TYPE_SLM,
    PRODUCT_CNC,
    PRODUCT_MIS,
    PRODUCT_NRML,
    REQUIRED_CANCEL_ALL_ORDER_FIELDS,
    REQUIRED_CANCEL_ORDER_FIELDS,
    REQUIRED_CLOSE_POSITION_FIELDS,
    REQUIRED_MODIFY_ORDER_FIELDS,
    REQUIRED_ORDER_FIELDS,
    REQUIRED_SMART_ORDER_FIELDS,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)

__all__ = [
    "ACTION_BUY",
    "ACTION_SELL",
    "CRYPTO_BROKERS",
    "CRYPTO_EXCHANGES",
    "CRYPTO_QUOTE_CURRENCY",
    "DEFAULT_DISCLOSED_QUANTITY",
    "DEFAULT_PRICE",
    "DEFAULT_PRICE_TYPE",
    "DEFAULT_PRODUCT_TYPE",
    "DEFAULT_TRIGGER_PRICE",
    "EXCHANGE_BADGE_COLORS",
    "EXCHANGE_BCD",
    "EXCHANGE_BFO",
    "EXCHANGE_BSE",
    "EXCHANGE_BSE_INDEX",
    "EXCHANGE_CDS",
    "EXCHANGE_CRYPTO",
    "EXCHANGE_MCX",
    "EXCHANGE_NCDEX",
    "EXCHANGE_NFO",
    "EXCHANGE_NSE",
    "EXCHANGE_NSE_INDEX",
    "FNO_EXCHANGES",
    "INSTRUMENT_PERPFUT",
    "LEGACY_INDIA_COMPATIBILITY",
    "PRICE_TYPE_LIMIT",
    "PRICE_TYPE_MARKET",
    "PRICE_TYPE_SL",
    "PRICE_TYPE_SLM",
    "PRODUCT_CNC",
    "PRODUCT_MIS",
    "PRODUCT_NRML",
    "REQUIRED_CANCEL_ALL_ORDER_FIELDS",
    "REQUIRED_CANCEL_ORDER_FIELDS",
    "REQUIRED_CLOSE_POSITION_FIELDS",
    "REQUIRED_MODIFY_ORDER_FIELDS",
    "REQUIRED_ORDER_FIELDS",
    "REQUIRED_SMART_ORDER_FIELDS",
    "VALID_ACTIONS",
    "VALID_EXCHANGES",
    "VALID_PRICE_TYPES",
    "VALID_PRODUCT_TYPES",
]
