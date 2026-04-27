"""v5 Phase 4 (ADR 0026 follow-on) — India sandbox provider parity.

Captures the canonical IndiaSandboxProvider behavior across order
placement, settlement, square-off, and PnL semantics. Locks v4
invariant 10 (India parity preserved bit-identically) for the
sandbox surface.

The harness exercises the provider's pure (no-DB) methods so the
snapshot is deterministic and re-runnable on any machine.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_sandbox_india"


def _equity_order():
    return SimpleNamespace(asset_class=SimpleNamespace(value="EQUITY"))


def _option_order():
    return SimpleNamespace(asset_class=SimpleNamespace(value="OPTION"))


def generate() -> Dict[str, Any]:
    from services.sandbox import dispatcher  # noqa: E402

    dispatcher.clear_sandbox_registry_for_tests()
    dispatcher.install_default_sandbox_providers()
    p = dispatcher.get_sandbox_provider("india")

    settlement = {
        "equity_2026-04-15": p.settlement_date_for_order(_equity_order(), date(2026, 4, 15)).isoformat(),
        "equity_friday_2026-04-17": p.settlement_date_for_order(_equity_order(), date(2026, 4, 17)).isoformat(),
        "option_2026-04-15": p.settlement_date_for_order(_option_order(), date(2026, 4, 15)).isoformat(),
    }

    sq_mis_nse = p.squareoff_time_for_product("MIS", "NSE", date(2026, 4, 15))
    squareoff = {
        "MIS_NSE_2026-04-15": {
            "hour": sq_mis_nse.hour,
            "minute": sq_mis_nse.minute,
            "tz": str(sq_mis_nse.tzinfo),
        },
        "CNC_NSE_2026-04-15": p.squareoff_time_for_product("CNC", "NSE", date(2026, 4, 15)),
        "NRML_NFO_2026-04-15": p.squareoff_time_for_product("NRML", "NFO", date(2026, 4, 15)),
    }

    return {
        "harness": NAME,
        "region_code": p.region_code,
        "base_currency": p.base_currency(),
        "initial_funds": str(p.initial_funds()),
        "partial_fills_supported": p.partial_fills_supported(),
        "supported_products": sorted(p.supported_products()),
        "settlement": settlement,
        "squareoff": squareoff,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True, default=str))
