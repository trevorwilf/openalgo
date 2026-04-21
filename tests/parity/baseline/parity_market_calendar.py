"""Parity harness: market calendar default timings.

Captures the literal `DEFAULT_MARKET_TIMINGS` dict from
`database.market_calendar_db` and a derived HH:MM rendering for each
Indian exchange plus CRYPTO. Phase 4 replaces the IST-midnight-offset
model with venue timezones; the fixture lets us detect any Phase 4
regression against the legacy Indian values.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_market_calendar"

EXCHANGES = ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "CRYPTO"]


def _offset_to_hhmm(offset_ms: int) -> str:
    hours = offset_ms // 3_600_000
    minutes = (offset_ms % 3_600_000) // 60_000
    return f"{hours:02d}:{minutes:02d}"


def generate() -> Dict[str, Any]:
    from database import market_calendar_db  # noqa: E402

    timings = {}
    for ex in EXCHANGES:
        entry = market_calendar_db.DEFAULT_MARKET_TIMINGS.get(ex)
        if entry is None:
            timings[ex] = None
            continue
        timings[ex] = {
            "start_offset_ms": int(entry["start_offset"]),
            "end_offset_ms": int(entry["end_offset"]),
            "start_hhmm": _offset_to_hhmm(entry["start_offset"]),
            "end_hhmm": _offset_to_hhmm(entry["end_offset"]),
        }

    return {
        "harness": NAME,
        "supported_exchanges": list(market_calendar_db.SUPPORTED_EXCHANGES),
        "timings": timings,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
