"""Parity harness: historify symbol validation.

Exercises `services.historify_service.validate_symbol` with a mocked
`get_symbol_info`. This is the path Phase 3b migrates (composite
`(symbol, exchange)` key continues to exist, `instrument_id` added
additively). The fixture ensures error wording is unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_historify_validate_symbol"

CASES = [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "NIFTY", "exchange": "NSE_INDEX"},  # index shortcut: always valid
    {"symbol": "SENSEX", "exchange": "BSE_INDEX"},
    {"symbol": "GHOST", "exchange": "NSE"},        # missing in master contract
    {"symbol": "BTCUSDT", "exchange": "CRYPTO"},
]


def _fake_get_symbol_info(symbol: str, exchange: str):
    known = {("RELIANCE", "NSE"), ("BTCUSDT", "CRYPTO")}
    if (symbol, exchange) in known:
        return {"symbol": symbol, "exchange": exchange, "token": "42"}
    return None


def generate() -> Dict[str, Any]:
    from services import historify_service  # noqa: E402

    results = []
    with mock.patch.object(historify_service, "get_symbol_info", side_effect=_fake_get_symbol_info):
        for case in CASES:
            ok, err = historify_service.validate_symbol(case["symbol"], case["exchange"])
            results.append({"input": case, "ok": ok, "error": err})
    return {"harness": NAME, "cases": results}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
