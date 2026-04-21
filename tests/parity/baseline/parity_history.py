"""Parity harness: history service validation layer.

Mirrors parity_quote's shape but against
`services.history_service.validate_symbol_exchange`. Captures the current
error messages so any v1 response-shape drift during the refactor is
caught.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_history"

CASES = [
    {"symbol": "INFY", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "bse"},
    {"symbol": "INFY", "exchange": "US_EQUITY"},
    {"symbol": "GHOST", "exchange": "NSE"},
    {"symbol": "ETHUSDT", "exchange": "CRYPTO"},
]


def _fake_get_token(symbol: str, exchange: str):
    known = {("INFY", "NSE"), ("INFY", "BSE"), ("ETHUSDT", "CRYPTO")}
    return "77777" if (symbol, exchange) in known else None


def generate() -> Dict[str, Any]:
    from services import history_service  # noqa: E402

    results = []
    with mock.patch.object(history_service, "get_token", side_effect=_fake_get_token):
        for case in CASES:
            ok, err = history_service.validate_symbol_exchange(case["symbol"], case["exchange"])
            results.append({"input": case, "ok": ok, "error": err})
    return {"harness": NAME, "cases": results}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
