"""v5 Phase 6 (ADR 0028 follow-on) — India Chartink screener parity.

Captures the canonical ChartinkScreenerProvider behavior across
webhook payload validation and signal-type inference. Locks v4
invariant 10 (India parity preserved bit-identically) for the
Chartink screener surface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_chartink_india"


def _scrub_signal(sig) -> dict:
    return {
        "signal_type": sig.signal_type,
        "symbols": list(sig.symbols),
        "price": str(sig.price) if sig.price is not None else None,
        "raw_payload_keys": sorted(sig.raw_payload.keys()),
    }


def generate() -> Dict[str, Any]:
    from services.screeners.providers.india.chartink import (  # noqa: E402
        ChartinkScreenerProvider,
        PROVIDER_CODE,
        REGION_CODE,
        SUPPORTED_VENUES,
    )

    p = ChartinkScreenerProvider()

    # Pin the validator output for representative payloads.
    payloads = {
        "bullish_breakout": {
            "stocks": "SBIN,RELIANCE,TCS",
            "trigger_prices": "525.5,2840.0,3500.0",
            "triggered_at": "2:34 pm",
            "scan_name": "Bullish Pattern",
            "alert_name": "Bullish Pattern Alert",
        },
        "bearish": {
            "stocks": "INFY",
            "trigger_prices": "1500.0",
            "triggered_at": "10:00 am",
            "scan_name": "Sell Signal",
            "alert_name": "Bearish Reversal",
        },
        "single_stock_no_price": {
            "stocks": "BANKBARODA",
            "triggered_at": "11:11 am",
            "scan_name": "Watch list",
            "alert_name": "Price alert",
        },
    }

    parsed = {
        name: _scrub_signal(p.validate_webhook_payload(payload))
        for name, payload in payloads.items()
    }

    return {
        "harness": NAME,
        "provider_code": PROVIDER_CODE,
        "region_code": REGION_CODE,
        "supported_venues": list(SUPPORTED_VENUES),
        "validated_signals": parsed,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True, default=str))
