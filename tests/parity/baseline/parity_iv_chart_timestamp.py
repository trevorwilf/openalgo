"""Parity harness: IV chart timestamp-to-IST conversion.

Exercises `services.iv_chart_service._convert_timestamp_to_ist` with
three timestamp-shape inputs (Unix seconds, Unix milliseconds, naive
string) and captures the resulting IST-indexed rows. Phase 4 replaces
this IST-only conversion with a venue-timezone lookup; v1 chart
responses remain IST-labelled so this fixture must keep passing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

import pandas as pd

NAME = "parity_iv_chart_timestamp"


def _to_jsonable(df) -> List[Dict[str, Any]]:
    """Turn a DataFrame with an IST DatetimeIndex into JSON rows."""
    out = []
    for idx, row in df.iterrows():
        out.append({
            "datetime_iso": idx.isoformat(),
            "timestamp": row.get("timestamp"),
            "open": float(row.get("open", 0)),
            "close": float(row.get("close", 0)),
        })
    return out


def generate() -> Dict[str, Any]:
    from services import iv_chart_service  # noqa: E402

    # Unix seconds — 2026-04-20 09:15:00 IST == 2026-04-20 03:45:00 UTC
    # = 1776993900 seconds since epoch.
    df_seconds = pd.DataFrame({
        "timestamp": [1776993900, 1776993960],
        "open": [100.0, 101.0],
        "close": [101.0, 102.0],
    })

    # Unix milliseconds — same two timestamps.
    df_ms = pd.DataFrame({
        "timestamp": [1776993900000, 1776993960000],
        "open": [100.0, 101.0],
        "close": [101.0, 102.0],
    })

    # Naive string (will be tz_localize("UTC") → tz_convert(IST))
    df_string = pd.DataFrame({
        "timestamp": ["2026-04-20 03:45:00", "2026-04-20 03:46:00"],
        "open": [100.0, 101.0],
        "close": [101.0, 102.0],
    })

    result = {}
    for label, df in (("unix_seconds", df_seconds),
                      ("unix_millis", df_ms),
                      ("naive_string", df_string)):
        out = iv_chart_service._convert_timestamp_to_ist(df.copy())
        result[label] = {
            "ok": out is not None,
            "rows": _to_jsonable(out) if out is not None else None,
        }

    return {"harness": NAME, "conversions": result}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
