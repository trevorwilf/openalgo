"""Live test: POST /api/v2/orders/<id>/modify on Alpaca paper."""
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

with httpx.Client(timeout=20.0) as c:
    # Place
    place = c.post(f"{BASE}/api/v2/orders", json={
        "apikey": API_KEY,
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY", "order_type": "LIMIT",
        "quantity": "1", "quantity_unit": "WHOLE",
        "time_in_force": "DAY", "session": "REGULAR",
        "price": "1.00",
    }).json()
    oid = (place.get("data") or {}).get("order_id")
    print(f"placed:   {oid} (limit=$1.00)")

    if not oid:
        print(f"  body: {json.dumps(place)[:300]}")
        sys.exit(1)
    time.sleep(0.5)

    # Modify via NEW v2 route
    r = c.post(f"{BASE}/api/v2/orders/{oid}/modify",
               json={"apikey": API_KEY, "price": "2.50", "quantity": "2"})
    print(f"modify:   HTTP {r.status_code}")
    body = r.json() if r.content else {}
    if r.status_code == 200:
        br = body.get("data", {}).get("broker_response", {})
        print(f"  Alpaca echo: status={br.get('status')} qty={br.get('qty')} "
              f"limit_price={br.get('limit_price')}")
    else:
        print(f"  body: {json.dumps(body)[:400]}")

    # Verify
    time.sleep(0.5)
    g = c.get(f"{BASE}/api/v2/orders/{oid}", params={"apikey": API_KEY}).json()
    o = (g.get("data") or {}).get("order") or {}
    print(f"readback: qty={o.get('qty')} limit_price={o.get('limit_price')} "
          f"status={o.get('status')}")

    # Modify with no fields → should 422
    r2 = c.post(f"{BASE}/api/v2/orders/{oid}/modify",
                json={"apikey": API_KEY})
    print(f"empty:    HTTP {r2.status_code} (expect 422)")

    # Cleanup
    c.delete(f"{BASE}/api/v2/orders/{oid}", params={"apikey": API_KEY})
    print("cleanup:  ok")
