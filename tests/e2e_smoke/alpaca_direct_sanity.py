"""Direct Alpaca paper API sanity — independent of OpenAlgo wiring.

Confirms ALPACA_API_KEY_ID / SECRET (or BROKER_API_KEY / SECRET) work
end-to-end against Alpaca's own /v2/account, /v2/positions, /v2/orders
and /v2/clock. Useful as a contrastive check: if these pass but the
OpenAlgo /api/v2 promoted-lane equivalents fail, the issue is in our
adapter, not in Alpaca.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# OpenAlgo .env names broker creds BROKER_API_KEY / BROKER_API_SECRET;
# the prefilter uses ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.
KEY = (os.environ.get("ALPACA_API_KEY_ID")
       or os.environ.get("BROKER_API_KEY") or "").strip(" '\"")
SECRET = (os.environ.get("ALPACA_API_SECRET_KEY")
          or os.environ.get("BROKER_API_SECRET") or "").strip(" '\"")
BASE = (os.environ.get("ALPACA_API_BASE")
        or "https://paper-api.alpaca.markets").strip(" '\"")
DATA_BASE = (os.environ.get("ALPACA_DATA_BASE")
             or "https://data.alpaca.markets").strip(" '\"")

if not KEY or not SECRET:
    print("missing Alpaca paper creds (BROKER_API_KEY/BROKER_API_SECRET in .env)")
    sys.exit(2)

HEADERS = {
    "APCA-API-KEY-ID": KEY,
    "APCA-API-SECRET-KEY": SECRET,
}


def call(client: httpx.Client, method: str, url: str, **kw):
    try:
        r = client.request(method, url, headers=HEADERS, timeout=20.0, **kw)
        body = r.json() if r.content else {}
        passed = r.status_code in (200, 207)
        sym = "OK" if passed else "FAIL"
        b = json.dumps(body)
        if len(b) > 200: b = b[:200] + "..."
        print(f"  {method:5s} {url:60s} -> {r.status_code} {sym}")
        print(f"    body: {b}")
        return {"url": url, "status": r.status_code, "passed": passed,
                "body_preview": b}
    except Exception as e:
        print(f"  {method:5s} {url:60s} -> EXC {e}")
        return {"url": url, "status": None, "passed": False, "exception": str(e)}


def main() -> int:
    results: list[dict] = []
    with httpx.Client() as c:
        print(f"=== Alpaca trading API ({BASE}) ===")
        results += [
            call(c, "GET", f"{BASE}/v2/account"),
            call(c, "GET", f"{BASE}/v2/account/configurations"),
            call(c, "GET", f"{BASE}/v2/positions"),
            call(c, "GET", f"{BASE}/v2/orders", params={"status": "all", "limit": "5"}),
            call(c, "GET", f"{BASE}/v2/clock"),
            call(c, "GET", f"{BASE}/v2/calendar", params={"start": "2026-05-05", "end": "2026-05-08"}),
            call(c, "GET", f"{BASE}/v2/assets/AAPL"),
        ]

        print(f"\n=== Alpaca data API ({DATA_BASE}) ===")
        results += [
            call(c, "GET", f"{DATA_BASE}/v2/stocks/AAPL/quotes/latest", params={"feed": "iex"}),
            call(c, "GET", f"{DATA_BASE}/v2/stocks/AAPL/bars",
                 params={"timeframe": "1Day", "start": "2026-04-01", "end": "2026-05-05",
                         "feed": "iex", "limit": "30"}),
            call(c, "GET", f"{DATA_BASE}/v2/stocks/AAPL/snapshot",
                 params={"feed": "iex"}),
        ]

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"\n[summary] {passed}/{total} passed")
    out = ROOT / "tests" / "e2e_smoke" / "_artifacts" / "alpaca_direct_results.json"
    out.write_text(json.dumps({"passed": passed, "total": total, "results": results}, indent=2))
    print(f"[done] -> {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
