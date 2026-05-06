"""Full v1 + v2 endpoint grid against Alpaca paper, market open.

Covers every endpoint the Alpaca compat shim is supposed to support
through both lanes. Helps surface any v1 surface that's broken even
while v2 takes over.
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
def call(method, path, **kw):
    started = time.perf_counter()
    expect = kw.pop("expect", (200,))
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.request(method, f"{BASE}{path}", **kw)
        elapsed = round((time.perf_counter() - started) * 1000)
        body = ""
        try:
            body = json.dumps(r.json(), default=str)[:300]
        except Exception:
            body = r.text[:200]
        passed = r.status_code in expect
        results.append({"method": method, "path": path, "status": r.status_code,
                        "ms": elapsed, "passed": passed, "body": body})
        print(f"  {method:5s} {path:45s} -> {r.status_code} ({elapsed}ms) "
              f"{'OK' if passed else 'FAIL'}")
        return r.status_code, body
    except Exception as e:
        results.append({"method": method, "path": path, "status": None,
                        "passed": False, "exception": str(e)})
        print(f"  {method:5s} {path:45s} -> EXC {e!s:.80}")
        return None, str(e)


def main() -> int:
    print("=== /api/v1 read surface ===")
    for path, body in [
        ("/api/v1/funds",       {"apikey": API_KEY}),
        ("/api/v1/orderbook",   {"apikey": API_KEY}),
        ("/api/v1/positionbook", {"apikey": API_KEY}),
        ("/api/v1/tradebook",   {"apikey": API_KEY}),
        ("/api/v1/holdings",    {"apikey": API_KEY}),
    ]:
        call("POST", path, json=body)

    print("\n=== /api/v1 market data ===")
    # Alpaca symbols routed through the legacy India-shaped quotes call.
    call("POST", "/api/v1/quotes",
         json={"apikey": API_KEY, "symbol": "AAPL", "exchange": "XNAS"},
         expect=(200, 400, 422))
    call("POST", "/api/v1/depth",
         json={"apikey": API_KEY, "symbol": "AAPL", "exchange": "XNAS"},
         expect=(200, 400, 422, 501))
    call("POST", "/api/v1/history",
         json={"apikey": API_KEY, "symbol": "AAPL", "exchange": "XNAS",
               "interval": "D", "start_date": "2026-04-01",
               "end_date": "2026-05-06"},
         expect=(200, 400, 422))
    call("POST", "/api/v1/intervals",
         json={"apikey": API_KEY},
         expect=(200, 404, 405))
    call("POST", "/api/v1/symbol",
         json={"apikey": API_KEY, "symbol": "AAPL", "exchange": "XNAS"},
         expect=(200, 400, 404))
    call("POST", "/api/v1/search",
         json={"apikey": API_KEY, "query": "AAPL", "exchange": "XNAS"},
         expect=(200, 400, 404))

    print("\n=== /api/v2 ===")
    call("GET", "/api/v2/balances", params={"apikey": API_KEY})
    call("GET", "/api/v2/positions", params={"apikey": API_KEY})
    call("GET", "/api/v2/orders", params={"apikey": API_KEY, "status": "all"})
    call("POST", "/api/v2/quotes", json={
        "apikey": API_KEY,
        "instruments": [{"venue_code": "XNAS", "canonical_symbol": "AAPL"}],
    })
    call("POST", "/api/v2/bars", json={
        "apikey": API_KEY,
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "interval": "1d", "start": "2026-04-01T00:00:00Z",
        "end": "2026-05-06T00:00:00Z",
    })
    # Newly-shipped v2 routes (no-op, paper safe).
    call("POST", "/api/v2/orders/closeposition", json={"apikey": API_KEY})

    print("\n=== /api/v2 read-only metadata ===")
    for path in ["/api/v2/regions", "/api/v2/regions/india", "/api/v2/regions/us",
                 "/api/v2/venues", "/api/v2/venues/XNAS",
                 "/api/v2/venues/XNAS/sessions",
                 "/api/v2/capabilities",
                 "/api/v2/plugins/diagnostics"]:
        params = {"apikey": API_KEY}
        if path.endswith("/sessions"):
            params["date"] = "2026-05-06"
        call("GET", path, params=params)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n[summary] {passed}/{total} passed")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print("\n--- failures ---")
        for r in failures:
            print(f"  {r['method']} {r['path']} status={r.get('status')} "
                  f"body={r.get('body','')[:200]}")

    (ART / "full_grid_results.json").write_text(json.dumps(results, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
