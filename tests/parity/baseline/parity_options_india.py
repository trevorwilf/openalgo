"""v5 Phase 5 (ADR 0027 follow-on) — India options provider parity.

Captures the canonical IndiaOptionsProvider behavior across symbol
parsing, expiry generation, and lot-size lookup. Locks v4 invariant
10 (India parity preserved bit-identically) for the options
surface.

The harness exercises the provider's pure (no-DB, no-network) methods
so the snapshot is deterministic and re-runnable on any machine.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_options_india"


def generate() -> Dict[str, Any]:
    from services.options.providers.india import IndiaOptionsProvider  # noqa: E402

    p = IndiaOptionsProvider()

    # Pin the parser for representative India symbols.
    parsed_samples = []
    for sym in (
        "NIFTY28MAR2420800CE",
        "BANKNIFTY28MAR2447500PE",
        "FINNIFTY15FEB2421000CE",
        "MIDCPNIFTY15FEB2410500PE",
        "SENSEX15FEB2475000CE",
        "BANKEX15FEB2455000PE",
    ):
        c = p.parse_option_symbol(sym)
        parsed_samples.append({
            "input": sym,
            "underlying": c.underlying,
            "expiry": c.expiry.isoformat(),
            "right": c.right.value if hasattr(c.right, "value") else str(c.right),
            "strike": str(c.strike),
            "lot_size": c.lot_size,
            "currency": c.currency,
            "venue_code": c.venue_code,
        })

    # Pin the formatter (round-trip).
    from services.options.providers.india import _format_ddmmmyy  # noqa: E402
    fmt_samples = []
    for sym in ("NIFTY28MAR2420800CE", "BANKNIFTY15FEB2447500.5PE"):
        try:
            c = p.parse_option_symbol(sym)
            fmt_samples.append({"input": sym, "round_trip": p.format_option_symbol(c)})
        except ValueError as e:
            fmt_samples.append({"input": sym, "error": str(e)})

    # Pin the expiry generator (8 weekly Thursdays from 2026-04-15).
    expiries = [
        d.isoformat() for d in p.list_expiries("NIFTY", date(2026, 4, 15))
    ]

    # Pin lot sizes for the canonical India underlyings.
    lot_sizes = {}
    for u in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"):
        # Build a contract just to invoke lot_size_for.
        c = p.parse_option_symbol(f"{u}28MAR2420000CE")
        lot_sizes[u] = p.lot_size_for(c)

    return {
        "harness": NAME,
        "region_code": p.region_code,
        "parsed_samples": parsed_samples,
        "fmt_samples": fmt_samples,
        "expiries_from_2026_04_15": expiries,
        "lot_sizes": lot_sizes,
        "supported_strategies": sorted(p.supported_strategies()),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True, default=str))
