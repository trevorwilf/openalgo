"""India quantity-freeze rules — Phase 2 T-12 relocation.

Source of truth for the NFO quantity-freeze table. Relocated
byte-equivalently from ``database/qty_freeze_db.py`` semantics:
NFO is the only Indian exchange today with a regulator-published
freeze table, loaded from ``data/qtyfreeze.csv``. Other Indian
exchanges (BFO, CDS, MCX) currently default to a freeze quantity
of 1 in the existing implementation.

The runtime cache and CSV loader stay in ``database/qty_freeze_db``
(PROMOTED_CORE) — this module documents the rule shape so the
``MarketRegion.quantity_freeze_rules`` field has a valid
India-shaped seed when consumers begin reading from it.

Each rule shape::

    {
        "venue": str,             # exchange code (NFO, BFO, ...)
        "underlying_pattern": str | None,  # symbol or pattern this applies to;
                                  # None means "all underlyings on this venue"
        "qty_freeze": int | None, # canonical freeze quantity; ``None`` for
                                  # "look up at runtime via the CSV cache"
        "default_qty_freeze": int,  # fallback when no specific entry matches
        "csv_source": str | None,
    }
"""

from __future__ import annotations

from typing import Any


# NFO has a per-underlying CSV-driven table; the entry below documents
# the venue-level fact, with the actual per-underlying numbers loaded
# at runtime from data/qtyfreeze.csv. Other Indian venues default to 1
# in the legacy implementation.
QUANTITY_FREEZE_RULES: list[dict[str, Any]] = [
    {
        "venue": "NFO",
        "underlying_pattern": None,
        "qty_freeze": None,
        "default_qty_freeze": 1,
        "csv_source": "data/qtyfreeze.csv",
    },
]


__all__ = ["QUANTITY_FREEZE_RULES"]
