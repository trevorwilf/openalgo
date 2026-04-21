"""Parity harness: place_order validation layer.

Exercises `services.place_order_service.validate_order_data` — the pure
pre-broker validation that screens for missing fields and invalid enums.
No broker network call. Captures the exact error-message text so any
v1 response drift is caught.

Circular-import note: `services.place_order_service` imports
`restx_api.schemas.OrderSchema`, and loading `restx_api/__init__.py`
transitively re-enters `services.place_order_service` before it has
finished initializing. That makes the module un-importable in a bare
harness. We work around this by pre-registering a minimal stub
`restx_api.schemas` in `sys.modules` with a pass-through `OrderSchema`.

The fixture therefore captures only the *pre-schema* validation layer
(field-present checks, exchange/action/price/product enum checks). The
marshmallow schema's own rules are covered by the broker tests. This is
the layer Phase 3a migrates and is the layer where v1 drift matters.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401


# Inject a stub restx_api / restx_api.schemas BEFORE importing
# services.place_order_service. Without this, the real restx_api/__init__.py
# causes a circular import through options_multiorder_service.
def _install_restx_stub() -> None:
    if "restx_api" in sys.modules and hasattr(sys.modules["restx_api"], "_parity_stub"):
        return

    schemas_module = types.ModuleType("restx_api.schemas")

    class OrderSchema:
        """Pass-through stub so the pre-schema validation layer can be exercised."""

        def load(self, data: Dict[str, Any]) -> Dict[str, Any]:
            return data

    schemas_module.OrderSchema = OrderSchema

    restx_module = types.ModuleType("restx_api")
    restx_module._parity_stub = True
    restx_module.schemas = schemas_module

    sys.modules["restx_api"] = restx_module
    sys.modules["restx_api.schemas"] = schemas_module


_install_restx_stub()

NAME = "parity_place_order_validation"

CASES = [
    {
        "label": "missing_all_required",
        "data": {},
    },
    {
        "label": "valid_market_order",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "price_type": "MARKET",
            "product_type": "MIS",
        },
    },
    {
        "label": "invalid_exchange",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "XNAS",
            "action": "BUY",
            "quantity": "1",
        },
    },
    {
        "label": "action_lowercase_gets_uppercased",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "buy",
            "quantity": "1",
        },
    },
    {
        "label": "invalid_action_bogus",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "TELEPORT",
            "quantity": "1",
        },
    },
    {
        "label": "invalid_price_type",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "price_type": "MOO",
        },
    },
    {
        "label": "invalid_product_type",
        "data": {
            "apikey": "fake",
            "strategy": "t",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "product_type": "GTC",
        },
    },
]


def generate() -> Dict[str, Any]:
    from services import place_order_service  # noqa: E402

    results = []
    for case in CASES:
        data = dict(case["data"])
        ok, validated, err = place_order_service.validate_order_data(data)
        results.append({
            "label": case["label"],
            "ok": ok,
            "error": err,
            "has_validated_data": validated is not None,
        })
    return {"harness": NAME, "cases": results}


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
