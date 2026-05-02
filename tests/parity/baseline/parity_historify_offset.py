"""Phase 7 v4 (ADR 0023) — historify venue-offset parity harness.

Captures the UTC offset returned by
:func:`database.venue_offset.venue_local_offset_seconds` for every
India venue across the year. Locks the contract that
``ist_offset = 19800`` for India venues year-round (Asia/Kolkata is
DST-free) so the v4 venue-aware refactor of historify_db's
aggregation queries cannot regress India aggregation.

Phase 1 (T-07) of the market-agnostic refactor: the helper no
longer returns 19800 for ``venue_code is None``; it raises
``VenueResolutionError``. The harness now pins both halves: the
9 India venue rows remain bit-identical at 19800, and the
``default_none_venue`` row records that the None branch is now a
fail-closed structured error. India aggregation is unaffected
because every historify call site supplies an explicit venue.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_historify_offset"

INDIA_VENUES = ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "BCD"]
SAMPLE_DATES = [
    date(2026, 1, 15),  # winter
    date(2026, 4, 15),  # spring
    date(2026, 7, 15),  # summer
    date(2026, 10, 15),  # fall
]


def generate() -> Dict[str, Any]:
    from database.venue_offset import venue_local_offset_seconds  # noqa: E402
    from domain.errors import VenueResolutionError  # noqa: E402

    out: Dict[str, Any] = {}
    for venue in INDIA_VENUES:
        per_date: Dict[str, int] = {}
        for d in SAMPLE_DATES:
            per_date[d.isoformat()] = venue_local_offset_seconds(venue, d)
        out[venue] = per_date
    # Phase 1 T-07: the None branch is now a fail-closed structured
    # error instead of a silent 19800. Pin the new contract.
    try:
        venue_local_offset_seconds()
    except VenueResolutionError:
        out["default_none_venue"] = "raises_VenueResolutionError"
    else:  # pragma: no cover — guard against regression
        out["default_none_venue"] = "did_not_raise"
    return {"harness": NAME, "venues": out}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
