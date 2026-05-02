"""Phase 9-bis-physical (T-23 Group B) — re-export shim.

The actual definitions live in
``market_regions.india.legacy_v1.translators`` after the physical
relocation. This module re-exports every public name so existing
``from domain.translators import normalized_order_to_legacy_fields``
(etc.) imports continue working without per-callsite changes.

Future engagements may incrementally migrate importers to the new
path and ultimately drop this shim.
"""

from __future__ import annotations

from market_regions.india.legacy_v1.translators import (  # noqa: F401
    legacy_exchange_to_venue_code,
    legacy_pricetype_to_order_type,
    legacy_product_to_order_attrs,
    market_family_for_legacy_exchange,
    normalized_order_to_legacy_fields,
)

__all__ = [
    "legacy_exchange_to_venue_code",
    "legacy_pricetype_to_order_type",
    "legacy_product_to_order_attrs",
    "market_family_for_legacy_exchange",
    "normalized_order_to_legacy_fields",
]
