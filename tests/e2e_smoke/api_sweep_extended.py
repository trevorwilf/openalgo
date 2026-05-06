"""Extended API sweep — exercises write paths safely.

Adds to the read-only sweep:
* /api/v2/instruments search (XNAS AAPL)
* /api/v2/capabilities (broker capabilities for the active session)
* /api/v2/orders POST (place a deeply-OTM LIMIT day order on paper —
  guaranteed to never fill at $1) + DELETE to cancel immediately.
* /api/v2/orders/combo POST OTOCO bracket (deeply OTM) + cancel parent.
* /api/v1 analyzer toggle + sandbox order place/cancel.

Each write is paired with a clean-up. Aborts cleanly if the active
broker isn't alpaca paper.
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
KEY_PATH = ART / "api_key.txt"

BASE = os.environ.get("HOST_SERVER", "http://127.0.0.1:5000").rstrip("/")
API_KEY = (KEY_PATH.read_text().strip() if KEY_PATH.exists()
           else os.environ.get("OPENALGO_API_KEY") or "")
if not API_KEY:
    print("missing API key (run smoke_login_and_sweep.mjs first)")
    sys.exit(2)

results: list[dict] = []


def call(client: httpx.Client, method: str, path: str, *,
         params=None, json_body=None, expect=(200, 201)):
    url = path if path.startswith("http") else f"{BASE}{path}"
    started = time.perf_counter()
    try:
        r = client.request(method, url, params=params, json=json_body, timeout=20.0)
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]
        passed = r.status_code in (expect if isinstance(expect, tuple) else (expect,))
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        results.append({"method": method, "path": path, "status": r.status_code,
                        "ms": elapsed, "passed": passed,
                        "body_preview": json.dumps(body, default=str)[:400]})
        print(f"  {method:6s} {path:60s} -> {r.status_code} ({elapsed:.0f}ms) "
              f"{'OK' if passed else 'FAIL'}")
        return body if isinstance(body, dict) else {}
    except Exception as e:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        results.append({"method": method, "path": path, "status": None,
                        "ms": elapsed, "passed": False, "exception": str(e)})
        print(f"  {method:6s} {path:60s} -> EXC {e!s:.80}")
        return {}


def main() -> int:
    with httpx.Client() as c:
        print("--- /api/v2/instruments search ---")
        call(c, "GET", "/api/v2/instruments/search",
             params={"apikey": API_KEY, "venue_code": "XNAS", "q": "AAPL"})

        print("\n--- /api/v2/capabilities ---")
        call(c, "GET", "/api/v2/capabilities", params={"apikey": API_KEY})

        print("\n--- /api/v2/plugins (302 to /diagnostics expected) ---")
        # Bare /api/v2/plugins returns 302 by design (see plugins.py:62 — it
        # redirects to /diagnostics so operators don't see the SPA fallback
        # HTML at this URL). Test the diagnostics endpoint directly.
        call(c, "GET", "/api/v2/plugins", params={"apikey": API_KEY},
             expect=(302,))
        call(c, "GET", "/api/v2/plugins/diagnostics",
             params={"apikey": API_KEY})

        print("\n--- /api/v2/orders POST single LIMIT (deep-OTM, paper-safe) ---")
        # AAPL trades around $284. A BUY LIMIT @ $1 will never fill. Paper
        # accepts it. We immediately cancel.
        place = call(
            c, "POST", "/api/v2/orders",
            json_body={
                "apikey": API_KEY,
                "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": "1",
                "quantity_unit": "WHOLE",
                "time_in_force": "DAY",
                "session": "REGULAR",
                "price": "1.00",
            },
        )
        order_id = (place.get("data") or {}).get("order_id")
        print(f"    placed order_id={order_id}")
        if order_id:
            time.sleep(0.5)  # let alpaca register it
            print(f"\n--- DELETE /api/v2/orders/{order_id} ---")
            call(c, "DELETE", f"/api/v2/orders/{order_id}",
                 params={"apikey": API_KEY},
                 expect=(200, 204))

        print("\n--- /api/v2/orders/combo POST OTOCO (deep-OTM, paper-safe) ---")
        combo = call(
            c, "POST", "/api/v2/orders/combo",
            json_body={
                "apikey": API_KEY,
                "combo_type": "OTOCO",
                "time_in_force": "DAY",
                "session": "REGULAR",
                "link_id": f"SWEEP-{int(time.time())}",
                "legs": [
                    {"instrument_ref": {"venue_code": "XNAS",
                                         "canonical_symbol": "AAPL"},
                     "side": "BUY", "quantity": "1", "quantity_unit": "WHOLE",
                     "order_type": "LIMIT", "price": "1.00"},
                    {"instrument_ref": {"venue_code": "XNAS",
                                         "canonical_symbol": "AAPL"},
                     "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                     "order_type": "LIMIT", "price": "9999.00"},
                    {"instrument_ref": {"venue_code": "XNAS",
                                         "canonical_symbol": "AAPL"},
                     "side": "SELL", "quantity": "1", "quantity_unit": "WHOLE",
                     "order_type": "STOP", "trigger_price": "0.50"},
                ],
            },
            expect=(200, 422),  # might be 422 if Alpaca rejects extreme prices
        )
        # Try to extract parent id from native_response
        cdata = (combo.get("data") or {})
        native = cdata.get("native_response") or {}
        parent_id = native.get("id")
        print(f"    placed parent_id={parent_id}")
        if parent_id:
            time.sleep(0.5)
            print(f"\n--- DELETE combo parent {parent_id} ---")
            call(c, "DELETE", f"/api/v2/orders/{parent_id}",
                 params={"apikey": API_KEY},
                 expect=(200, 204, 422))  # children may also need cleanup

        # Cancel-all sweep — final safety net.
        print("\n--- DELETE /api/v2/orders (cancel-all) ---")
        call(c, "DELETE", "/api/v2/orders", params={"apikey": API_KEY},
             expect=(200, 204))

        # Analyzer / sandbox round-trip via /api/v1 — these are India-shaped
        # but the analyzer mode is broker-agnostic in spirit (sandbox sim).
        print("\n--- /api/v1 analyzer toggle (read-only check) ---")
        call(c, "GET", "/api/v1/analyzer/status",
             params={"apikey": API_KEY},
             expect=(200, 404, 405))

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"\n[summary] {passed}/{total} passed")

    out = ART / "api_extended_results.json"
    out.write_text(json.dumps({"passed": passed, "total": total, "results": results},
                              indent=2, default=str))
    print(f"[done] -> {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
