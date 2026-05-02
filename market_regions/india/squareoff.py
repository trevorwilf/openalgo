"""India MIS auto-square-off rules — Phase 2 T-11 relocation.

Source of truth for the MIS auto-square-off times per Indian
exchange. Relocated byte-equivalently from the legacy defaults that
``sandbox/squareoff_manager.py`` reads via the ``get_config(...)``
fallbacks (``nse_bse_square_off_time=15:15``, ``cds_bcd_square_off_time
=16:45``, ``mcx_square_off_time=23:30``, ``ncdex_square_off_time=
17:00``).

The runtime engine still reads from the sandbox config table so
operator overrides continue to work; this module documents the
default values and provides them in the
``MarketRegion.mandatory_close_rules``-shaped form that future
phases (and US/EU squareoff providers) consume.

Schema for each entry::

    {
        "venue": str,                  # exchange code (NSE, BSE, ...)
        "local_close": "HH:MM",        # in venue-local time (Asia/Kolkata)
        "applies_to": list[str],       # product codes this rule covers
    }
"""

from __future__ import annotations

from typing import Any


MANDATORY_CLOSE_RULES: list[dict[str, Any]] = [
    {"venue": "NSE", "local_close": "15:15", "applies_to": ["MIS"]},
    {"venue": "BSE", "local_close": "15:15", "applies_to": ["MIS"]},
    {"venue": "NFO", "local_close": "15:15", "applies_to": ["MIS"]},
    {"venue": "BFO", "local_close": "15:15", "applies_to": ["MIS"]},
    {"venue": "CDS", "local_close": "16:45", "applies_to": ["MIS"]},
    {"venue": "BCD", "local_close": "16:45", "applies_to": ["MIS"]},
    {"venue": "MCX", "local_close": "23:30", "applies_to": ["MIS"]},
    {"venue": "NCDEX", "local_close": "17:00", "applies_to": ["MIS"]},
]


__all__ = ["MANDATORY_CLOSE_RULES"]
