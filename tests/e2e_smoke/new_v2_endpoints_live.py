"""Live test of the freshly-shipped /api/v2 endpoints (this round):
   GET /api/v2/trades
   GET /api/v2/holdings
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
def call(c, method, path, **kw):
    started = time.perf_counter()
    expect = kw.pop("expect", (200,))
    r = c.request(method, f"{BASE}{path}", timeout=20.0, **kw)
    elapsed = round((time.perf_counter() - started) * 1000)
    body = {}
    try: body = r.json()
    except Exception: pass
    passed = r.status_code in expect
    results.append({"method": method, "path": path, "status": r.status_code,
                    "ms": elapsed, "passed": passed,
                    "body": json.dumps(body, default=str)[:300]})
    print(f"  {method:5s} {path:40s} -> {r.status_code} ({elapsed}ms) "
          f"{'OK' if passed else 'FAIL'}")
    return body


with httpx.Client() as c:
    print("=== /api/v2/trades ===")
    body = call(c, "GET", "/api/v2/trades", params={"apikey": API_KEY})
    trades = body.get("data", {}).get("trades", [])
    print(f"     count={body.get('data', {}).get('count', '?')}")
    if trades:
        t = trades[0]
        print(f"     latest fill: symbol={t.get('symbol')} side={t.get('side')} "
              f"qty={t.get('qty')} price={t.get('price')} time={t.get('transaction_time')}")

    print("\n=== /api/v2/trades?date=today ===")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    body = call(c, "GET", "/api/v2/trades",
                 params={"apikey": API_KEY, "date": today, "page_size": "20"})
    print(f"     count_today={body.get('data', {}).get('count', '?')}")

    print("\n=== /api/v2/holdings ===")
    body = call(c, "GET", "/api/v2/holdings", params={"apikey": API_KEY})
    holdings = body.get("data", {}).get("holdings", [])
    print(f"     count={body.get('data', {}).get('count', '?')}")
    for h in holdings:
        print(f"     {h.get('symbol')} qty={h.get('qty')} avg={h.get('avg_entry_price')}")

    # Compare /api/v2/holdings to /api/v2/positions — for Alpaca they
    # should return the same set.
    print("\n=== /api/v2/positions (compare) ===")
    body = call(c, "GET", "/api/v2/positions", params={"apikey": API_KEY})
    print(f"     positions count={len(body.get('data', {}).get('positions', []))}")

    # Bad inputs.
    print("\n=== /api/v2/trades?page_size=99999 (expect 400) ===")
    call(c, "GET", "/api/v2/trades",
         params={"apikey": API_KEY, "page_size": "99999"},
         expect=(400,))

    print("\n=== /api/v2/trades (no apikey, expect 401) ===")
    call(c, "GET", "/api/v2/trades", expect=(401,))

passed = sum(1 for r in results if r["passed"])
total = len(results)
print(f"\n[summary] {passed}/{total} passed")
sys.exit(0 if passed == total else 1)
