"""Live test for the new v2 routes shipped this round:
   POST /api/v2/orders/cancelall
   POST /api/v2/orders/<id>/cancel
   POST /api/v2/orders/closeposition

Each is paired with cleanup. Designed for paper account safety.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "tests" / "e2e_smoke" / "_artifacts"
API_KEY = (ART / "api_key.txt").read_text().strip()
BASE = "http://127.0.0.1:5000"

results = []
def call(c, method, path, *, expect=(200,), json_body=None, params=None):
    started = time.perf_counter()
    r = c.request(method, f"{BASE}{path}", json=json_body, params=params,
                   timeout=20.0)
    elapsed = round((time.perf_counter() - started) * 1000)
    body = {}
    try: body = r.json()
    except Exception: pass
    passed = r.status_code in expect
    out = {"method": method, "path": path, "status": r.status_code,
           "ms": elapsed, "passed": passed,
           "body": json.dumps(body, default=str)[:300]}
    results.append(out)
    print(f"  {method:6s} {path:55s} -> {r.status_code} ({elapsed}ms) "
          f"{'OK' if passed else 'FAIL'}")
    return body

with httpx.Client() as c:
    print("--- 1. POST /api/v2/orders/<id>/cancel (alias) ---")
    place = call(c, "POST", "/api/v2/orders", json_body={
        "apikey": API_KEY,
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY", "order_type": "LIMIT",
        "quantity": "1", "quantity_unit": "WHOLE",
        "time_in_force": "DAY", "session": "REGULAR", "price": "1.00",
    })
    oid = (place.get("data") or {}).get("order_id")
    print(f"     placed {oid}")
    time.sleep(0.5)
    call(c, "POST", f"/api/v2/orders/{oid}/cancel",
         json_body={"apikey": API_KEY})

    print("\n--- 2. POST /api/v2/orders/cancelall (alias) ---")
    # Place 3 far-OTM LIMIT orders, then cancel-all.
    placed_ids = []
    for i in range(3):
        p = call(c, "POST", "/api/v2/orders", json_body={
            "apikey": API_KEY,
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "side": "BUY", "order_type": "LIMIT",
            "quantity": "1", "quantity_unit": "WHOLE",
            "time_in_force": "DAY", "session": "REGULAR",
            "price": str(0.50 + i * 0.10),
        })
        oid = (p.get("data") or {}).get("order_id")
        placed_ids.append(oid)
    print(f"     placed: {placed_ids}")
    time.sleep(0.5)
    cancel_all = call(c, "POST", "/api/v2/orders/cancelall",
                       json_body={"apikey": API_KEY})
    summary = (cancel_all.get("data") or {}).get("summary", {})
    print(f"     summary: canceled={summary.get('canceled_count')} "
          f"failed={summary.get('failed_count')}")

    print("\n--- 3. POST /api/v2/orders/closeposition (no instrument = all) ---")
    # Account is flat (paper $100K cash) so close-all should return [].
    body = call(c, "POST", "/api/v2/orders/closeposition",
                 json_body={"apikey": API_KEY})
    br = body.get("data", {}).get("broker_response", {})
    print(f"     status={br.get('status')} closed_count={len(br.get('data') or [])}")

    print("\n--- 4. POST /api/v2/orders/closeposition (specific symbol) ---")
    # No AAPL position exists, so we expect Alpaca's 404 → 502 with code 40410000.
    body = call(c, "POST", "/api/v2/orders/closeposition",
                 json_body={
                     "apikey": API_KEY,
                     "instrument": {"venue_code": "XNAS",
                                    "canonical_symbol": "AAPL"},
                 },
                 expect=(200, 502))
    if not body.get("error"):
        print(f"     status={body.get('data', {}).get('status')}")
    else:
        msg = body["error"]["message"]
        print(f"     expected 502: {msg[:100]}")

    # Final cleanup safety net
    print("\n--- 5. final cleanup (DELETE /api/v2/orders) ---")
    call(c, "DELETE", "/api/v2/orders", params={"apikey": API_KEY})

passed = sum(1 for r in results if r["passed"])
total = len(results)
print(f"\n[summary] {passed}/{total} passed")
sys.exit(0 if passed == total else 1)
