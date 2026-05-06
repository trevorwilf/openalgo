"""Place LIMIT, modify price, cancel — covers /api/v1/modifyorder.

v2 doesn't expose modify yet (only POST/GET/DELETE). Modify is wired
through the v1 lane via the Alpaca compat shim.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "tests" / "e2e_smoke" / "_artifacts"
API_KEY = (ART / "api_key.txt").read_text().strip()
BASE = "http://127.0.0.1:5000"


def main() -> int:
    with httpx.Client(timeout=20.0) as c:
        # Place via /api/v2/orders (we know this works) — far-OTM LIMIT.
        place = c.post(f"{BASE}/api/v2/orders", json={
            "apikey": API_KEY,
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "side": "BUY", "order_type": "LIMIT",
            "quantity": "1", "quantity_unit": "WHOLE",
            "time_in_force": "DAY", "session": "REGULAR",
            "price": "1.00",
        }).json()
        oid = (place.get("data") or {}).get("order_id")
        print(f"placed: {oid}")
        if not oid:
            print(f"  body: {json.dumps(place)[:300]}")
            return 1

        # Modify via /api/v1/modifyorder.
        time.sleep(0.5)
        modify = c.post(f"{BASE}/api/v1/modifyorder", json={
            "apikey": API_KEY,
            "orderid": oid,
            "strategy": "smoke-test",
            "symbol": "AAPL",
            "exchange": "XNAS",
            "action": "BUY",
            "product": "CNC",
            "pricetype": "LIMIT",
            "quantity": "1",
            "price": "2.00",
        })
        body = modify.json() if modify.content else {}
        print(f"modify: HTTP {modify.status_code} {json.dumps(body)[:300]}")

        # Verify by reading back via /api/v2/orders/<id>
        time.sleep(0.5)
        get_r = c.get(f"{BASE}/api/v2/orders/{oid}",
                       params={"apikey": API_KEY})
        get_body = get_r.json() if get_r.content else {}
        order = (get_body.get("data") or {}).get("order") or {}
        print(f"get: HTTP {get_r.status_code} order_status={order.get('status')} "
              f"limit_price={order.get('limit_price')}")

        # Cleanup.
        cancel = c.delete(f"{BASE}/api/v2/orders/{oid}",
                          params={"apikey": API_KEY})
        print(f"cancel: HTTP {cancel.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
