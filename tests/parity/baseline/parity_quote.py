"""Parity harness: quote service validation layer.

Exercises `services.quotes_service.validate_symbol_exchange` with a mocked
`get_token` so the fixture is independent of any downloaded symbol table.
The intent is to freeze the current validation rules (VALID_EXCHANGES,
error message text) so later phases surface any change.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest import mock

# Must precede project imports — sets DATABASE_URL etc.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

NAME = "parity_quote"

CASES = [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "reliance", "exchange": "nse"},   # case-insensitive exchange
    {"symbol": "RELIANCE", "exchange": "XNAS"},  # invalid exchange
    {"symbol": "NONEXISTENT", "exchange": "NSE"},
    {"symbol": "BTCUSDT", "exchange": "CRYPTO"},
    {"symbol": "NIFTY28MAR2420800CE", "exchange": "NFO"},
]


def _fake_get_token(symbol: str, exchange: str):
    """Deterministic stand-in for database.token_db.get_token."""
    known = {
        ("RELIANCE", "NSE"),
        ("BTCUSDT", "CRYPTO"),
        ("NIFTY28MAR2420800CE", "NFO"),
    }
    return "99999" if (symbol, exchange) in known else None


def generate() -> Dict[str, Any]:
    from services import quotes_service  # noqa: E402

    results = []
    with mock.patch.object(quotes_service, "get_token", side_effect=_fake_get_token):
        for case in CASES:
            ok, err = quotes_service.validate_symbol_exchange(case["symbol"], case["exchange"])
            results.append({"input": case, "ok": ok, "error": err})
    return {"harness": NAME, "cases": results}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
