"""End-to-end live trade test:
   1. Place 1 share AAPL MARKET BUY → fills immediately at market open.
   2. Verify position appears.
   3. Close the position via POST /api/v2/orders/closeposition.
   4. Verify position cleared.

Paper account; 1 share so cost is ~$280 against $100K balance.
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


def call(c, method, path, **kw):
    started = time.perf_counter()
    r = c.request(method, f"{BASE}{path}", timeout=20.0, **kw)
    elapsed = round((time.perf_counter() - started) * 1000)
    body = {}
    try: body = r.json()
    except Exception: body = {"_raw": r.text[:200]}
    print(f"  {method:6s} {path:55s} -> {r.status_code} ({elapsed}ms)")
    return r.status_code, body


def main() -> int:
    with httpx.Client() as c:
        print("[1] place 1 AAPL MARKET BUY")
        status, body = call(c, "POST", "/api/v2/orders", json={
            "apikey": API_KEY,
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "side": "BUY", "order_type": "MARKET",
            "quantity": "1", "quantity_unit": "WHOLE",
            "time_in_force": "DAY", "session": "REGULAR",
        })
        if status != 200:
            print(f"     PLACE FAILED: {json.dumps(body)[:300]}")
            return 1
        oid = body.get("data", {}).get("order_id")
        print(f"     order_id={oid}")

        # Wait for fill (market is open, MARKET order should fill in seconds).
        print("\n[2] poll for fill (60s timeout)")
        for attempt in range(60):
            time.sleep(1.0)
            status, body = call(c, "GET", f"/api/v2/orders/{oid}",
                                 params={"apikey": API_KEY})
            order = (body.get("data") or {}).get("order") or {}
            ofs = order.get("status") or order.get("native_status")
            if ofs in ("filled", "FILLED"):
                print(f"     FILLED at {order.get('filled_avg_price')}")
                break
            print(f"     attempt {attempt}: status={ofs}")
        else:
            print("     timed out waiting for fill")
            # cleanup just in case
            call(c, "DELETE", "/api/v2/orders", params={"apikey": API_KEY})
            return 2

        print("\n[3] verify position via /api/v2/positions")
        status, body = call(c, "GET", "/api/v2/positions",
                             params={"apikey": API_KEY})
        positions = body.get("data", {}).get("positions", [])
        aapl = next((p for p in positions if p.get("canonical_symbol") == "AAPL"), None)
        print(f"     positions={len(positions)} AAPL_qty={aapl.get('quantity') if aapl else None}")
        if aapl is None:
            print("     POSITION NOT VISIBLE — bug or timing")
            return 3

        print("\n[4] close AAPL via POST /api/v2/orders/closeposition")
        status, body = call(c, "POST", "/api/v2/orders/closeposition", json={
            "apikey": API_KEY,
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        })
        if status != 200:
            print(f"     CLOSE FAILED: {json.dumps(body)[:300]}")
            return 4
        print(f"     close response: {json.dumps(body.get('data', {}))[:300]}")

        print("\n[5] poll positions until flat")
        for attempt in range(10):
            time.sleep(0.5)
            status, body = call(c, "GET", "/api/v2/positions",
                                 params={"apikey": API_KEY})
            positions = body.get("data", {}).get("positions", [])
            still_aapl = any(p.get("canonical_symbol") == "AAPL" for p in positions)
            if not still_aapl:
                print(f"     CLEARED")
                break
            print(f"     attempt {attempt}: still {len(positions)} positions")
        else:
            print("     position did not clear — manual cleanup required")
            return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
