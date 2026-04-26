"""Phase 7 v4 (ADR 0023) — historify venue-offset parity harness.

Captures the UTC offset returned by
:func:`database.venue_offset.venue_local_offset_seconds` for every
India venue across the year. Locks the contract that
``ist_offset = 19800`` for India venues year-round (Asia/Kolkata is
DST-free) so the v4 venue-aware refactor of historify_db's
aggregation queries cannot regress India aggregation.
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

    out: Dict[str, Any] = {}
    for venue in INDIA_VENUES:
        per_date: Dict[str, int] = {}
        for d in SAMPLE_DATES:
            per_date[d.isoformat()] = venue_local_offset_seconds(venue, d)
        out[venue] = per_date
    out["default_unknown_venue"] = venue_local_offset_seconds()
    return {"harness": NAME, "venues": out}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
