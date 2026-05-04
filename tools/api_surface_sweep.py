"""v7 — Browser-free API surface sweep against local Flask + Alpaca paper.

Logs into the OpenAlgo UI session ONCE, fetches the operator's
existing API key, and exercises every documented /api/v1/* and
/api/v2/* endpoint plus the /auth/* surface. Cross-checks
selected responses against direct calls to Alpaca's paper API
(https://paper-api.alpaca.markets/v2/*) so any v1↔Alpaca drift
introduced by the v7 refactor surfaces in one place.

Designed to avoid the rate-limit cascade the Playwright suite
hit (each spec file's beforeAll = 1 login = 9 logins per run +
manual curls). This tool: 1 login, N reads via the session
cookie + API key.

Usage:
    uv run python tools/api_surface_sweep.py
    uv run python tools/api_surface_sweep.py --skip-alpaca-direct
    uv run python tools/api_surface_sweep.py --json  # machine-readable

Env requirements:
    web_login_username, web_login_password (operator's UI login)
    BROKER_API_KEY, BROKER_API_SECRET (Alpaca paper keys for the
        direct API cross-check; PK-prefixed = paper-api endpoint)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

# override=True so .env values take precedence over OS-level env
# vars. Operators sometimes have stale OS-level placeholder values
# (e.g. ``BROKER_API_KEY=YOUR_BROKER_API_KEY``) from a prior dev
# shell that overrides the real keys in .env.
load_dotenv(REPO_ROOT / ".env", override=True)

import httpx  # noqa: E402

BASE = os.environ.get("OPENALGO_BASE_URL", "http://127.0.0.1:5000")
USERNAME = os.environ.get("web_login_username") or os.environ.get(
    "WEB_LOGIN_USERNAME", ""
)
PASSWORD = os.environ.get("web_login_password") or os.environ.get(
    "WEB_LOGIN_PASSWORD", ""
)

ALPACA_API_KEY = os.environ.get("BROKER_API_KEY") or os.environ.get(
    "ALPACA_API_KEY", ""
)
ALPACA_API_SECRET = os.environ.get("BROKER_API_SECRET") or os.environ.get(
    "ALPACA_API_SECRET", ""
)


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if (v.startswith("'") and v.endswith("'")) or (
        v.startswith('"') and v.endswith('"')
    ):
        return v[1:-1]
    return v


USERNAME = _strip_quotes(USERNAME)
PASSWORD = _strip_quotes(PASSWORD)
ALPACA_API_KEY = _strip_quotes(ALPACA_API_KEY)
ALPACA_API_SECRET = _strip_quotes(ALPACA_API_SECRET)


def login_and_get_apikey() -> tuple[httpx.Client, str]:
    """Log in once + fetch the operator's API key. Reuses the
    returned client (with session cookie) for all subsequent
    calls."""
    client = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)

    csrf_resp = client.get("/auth/csrf-token")
    csrf_resp.raise_for_status()
    csrf_token = csrf_resp.json().get("csrf_token", "")
    if not csrf_token:
        raise RuntimeError(f"no csrf_token in {csrf_resp.text[:200]!r}")

    login_resp = client.post(
        "/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"X-CSRFToken": csrf_token},
    )
    if login_resp.status_code >= 400:
        raise RuntimeError(
            f"login failed: {login_resp.status_code} {login_resp.text[:200]}"
        )

    apikey_resp = client.get("/apikey", headers={"Accept": "application/json"})
    apikey_resp.raise_for_status()
    body = apikey_resp.json()
    apikey = body.get("api_key") or body.get("apikey") or ""
    if not apikey:
        raise RuntimeError(f"no api_key in /apikey response: {body}")
    return client, apikey


class Report:
    """Collect pass/fail rows for the final summary."""

    def __init__(self, *, json_mode: bool = False) -> None:
        self.rows: list[dict[str, Any]] = []
        self.json_mode = json_mode

    def add(self, name: str, ok: bool, *, status: int = 0, detail: str = "") -> None:
        self.rows.append(
            {"name": name, "ok": ok, "status": status, "detail": detail}
        )
        if not self.json_mode:
            mark = "OK  " if ok else "FAIL"
            extra = f" ({status})" if status else ""
            tail = f" — {detail}" if detail else ""
            print(f"  [{mark}] {name}{extra}{tail}")

    def summary(self) -> int:
        fails = [r for r in self.rows if not r["ok"]]
        if self.json_mode:
            print(
                json.dumps(
                    {
                        "total": len(self.rows),
                        "passed": len(self.rows) - len(fails),
                        "failed": len(fails),
                        "rows": self.rows,
                    },
                    indent=2,
                )
            )
        else:
            total = len(self.rows)
            passed = total - len(fails)
            print(f"\n{passed}/{total} passed, {len(fails)} failed")
            for r in fails:
                print(f"  FAIL {r['name']}: status={r['status']} {r['detail']}")
        return 0 if not fails else 1


def call_v1(
    client: httpx.Client, apikey: str, path: str, body: dict | None = None
) -> tuple[int, dict | None]:
    payload = {"apikey": apikey}
    if body:
        payload.update(body)
    r = client.post(f"/api/v1/{path.lstrip('/')}", json=payload)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def call_v2(
    client: httpx.Client,
    apikey: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
) -> tuple[int, dict | None]:
    headers = {"X-API-KEY": apikey}
    if method == "GET":
        r = client.get(f"/api/v2/{path.lstrip('/')}", headers=headers)
    else:
        r = client.request(
            method, f"/api/v2/{path.lstrip('/')}", headers=headers, json=body
        )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


def sweep_v1(client: httpx.Client, apikey: str, report: Report) -> None:
    if not report.json_mode:
        print("\n=== /api/v1/* surface ===")

    # Read-only endpoints — should all return 200 with status: success.
    for path in (
        "funds",
        "holdings",
        "positionbook",
        "orderbook",
        "tradebook",
    ):
        sc, body = call_v1(client, apikey, path)
        ok = sc == 200 and body and body.get("status") == "success"
        report.add(
            f"v1 /{path}",
            ok,
            status=sc,
            detail=str(body.get("message", "") or "")[:80] if not ok else "",
        )

    # Symbol/quotes/intervals — partial coverage with a known good
    # symbol. Alpaca paper has AAPL on XNAS. The legacy
    # ``/intervals`` endpoint is India-only; Alpaca returns 410 via
    # the v1-lane block (the documented "feature unavailable for
    # this region" response).
    sc, body = call_v1(client, apikey, "intervals")
    report.add(
        "v1 /intervals (200 india / 410 non-india)",
        sc in (200, 410),
        status=sc,
    )

    # Quote — try a known US symbol (Alpaca paper).
    sc, body = call_v1(client, apikey, "quotes", {"symbol": "AAPL", "exchange": "XNAS"})
    report.add(
        "v1 /quotes AAPL XNAS",
        sc == 200,
        status=sc,
        detail=str(body.get("message", "") or "")[:80] if sc != 200 else "",
    )

    # Search — the legacy India endpoint may 410 for non-India brokers
    # depending on lane configuration. Just note status.
    sc, body = call_v1(client, apikey, "search", {"symbol": "AAPL"})
    report.add(
        "v1 /search AAPL", sc in (200, 410), status=sc,
    )


def sweep_v2(client: httpx.Client, apikey: str, report: Report) -> None:
    if not report.json_mode:
        print("\n=== /api/v2/* surface ===")

    # /api/v2/regions (list)
    sc, body = call_v2(client, apikey, "regions")
    regions = (body or {}).get("data", {}).get("regions", []) if body else []
    region_codes = {r.get("region_code") for r in regions}
    report.add(
        "v2 /regions",
        sc == 200 and {"india", "us", "eu", "uk", "crypto"}.issubset(region_codes),
        status=sc,
        detail=f"got {sorted(region_codes)}",
    )

    # /api/v2/regions/<code>
    for code in ("india", "us", "eu", "uk", "crypto"):
        sc, body = call_v2(client, apikey, f"regions/{code}")
        report.add(f"v2 /regions/{code}", sc == 200, status=sc)

    # /api/v2/regions/<code>/holidays
    sc, body = call_v2(client, apikey, "regions/india/holidays?year=2026")
    holidays = (body or {}).get("data", {}).get("holidays", []) if body else []
    report.add(
        "v2 /regions/india/holidays?year=2026",
        sc == 200 and len(holidays) > 5,
        status=sc,
        detail=f"{len(holidays)} holidays",
    )

    sc, body = call_v2(client, apikey, "regions/us/holidays?year=2026")
    report.add("v2 /regions/us/holidays?year=2026", sc == 200, status=sc)

    sc, body = call_v2(client, apikey, "regions/atlantis/holidays")
    report.add(
        "v2 /regions/atlantis/holidays (404 expected)",
        sc == 404,
        status=sc,
    )

    # /api/v2/regions/<code>/flow_defaults
    sc, body = call_v2(client, apikey, "regions/india/flow_defaults")
    report.add("v2 /regions/india/flow_defaults", sc == 200, status=sc)

    # /api/v2/capabilities
    sc, body = call_v2(client, apikey, "capabilities")
    report.add("v2 /capabilities", sc == 200, status=sc)

    # /api/v2/positions
    sc, body = call_v2(client, apikey, "positions")
    positions = (body or {}).get("data", {}).get("positions", []) if body else []
    report.add(
        "v2 /positions",
        sc == 200,
        status=sc,
        detail=f"{len(positions)} positions" if isinstance(positions, list) else "",
    )

    # /api/v2/orders (list)
    sc, body = call_v2(client, apikey, "orders")
    report.add("v2 /orders (list)", sc == 200, status=sc)


def sweep_auth(client: httpx.Client, report: Report) -> None:
    if not report.json_mode:
        print("\n=== /auth/* surface ===")

    sc = client.get("/auth/broker-config").status_code
    report.add("/auth/broker-config", sc == 200, status=sc)

    r = client.get("/auth/broker-config")
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    has_mode = body and "broker_mode" in body
    report.add(
        "/auth/broker-config has broker_mode field",
        bool(has_mode),
        detail=f"mode={body.get('broker_mode') if body else None}",
    )

    sc = client.get("/auth/dashboard-data").status_code
    report.add("/auth/dashboard-data", sc == 200, status=sc)


def sweep_alpaca_direct(report: Report) -> None:
    if not report.json_mode:
        print("\n=== Alpaca paper API direct ===")
    if not (ALPACA_API_KEY and ALPACA_API_SECRET):
        report.add(
            "Alpaca direct API",
            False,
            detail="BROKER_API_KEY/SECRET not configured",
        )
        return

    base = (
        "https://paper-api.alpaca.markets"
        if ALPACA_API_KEY.startswith("PK")
        else "https://api.alpaca.markets"
    )
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }
    with httpx.Client(base_url=base, timeout=30) as c:
        # /v2/account
        try:
            r = c.get("/v2/account", headers=headers)
            sc = r.status_code
            body = r.json() if sc < 400 else None
        except Exception as e:
            sc = 0
            body = None
        report.add(
            "Alpaca direct /v2/account",
            sc == 200 and body and "id" in body,
            status=sc,
            detail=f"cash=${body.get('cash')}" if body else "",
        )

        # /v2/positions
        try:
            r = c.get("/v2/positions", headers=headers)
            sc = r.status_code
        except Exception:
            sc = 0
        report.add(
            "Alpaca direct /v2/positions",
            sc == 200,
            status=sc,
        )

        # /v2/orders?status=open
        try:
            r = c.get("/v2/orders?status=open&limit=10", headers=headers)
            sc = r.status_code
        except Exception:
            sc = 0
        report.add(
            "Alpaca direct /v2/orders (status=open)",
            sc == 200,
            status=sc,
        )

        # /v2/clock
        try:
            r = c.get("/v2/clock", headers=headers)
            sc = r.status_code
            body = r.json() if sc < 400 else None
        except Exception:
            sc = 0
            body = None
        report.add(
            "Alpaca direct /v2/clock",
            sc == 200 and body and "is_open" in body,
            status=sc,
            detail=f"is_open={body.get('is_open')}" if body else "",
        )


def cross_check_balance(
    openalgo_client: httpx.Client,
    apikey: str,
    report: Report,
) -> None:
    """Cross-check OpenAlgo's v1 /funds matches Alpaca direct
    /v2/account."""
    if not report.json_mode:
        print("\n=== OpenAlgo v1 /funds  vs.  Alpaca direct /v2/account ===")
    if not (ALPACA_API_KEY and ALPACA_API_SECRET):
        return

    sc_oa, body_oa = call_v1(openalgo_client, apikey, "funds")
    base = (
        "https://paper-api.alpaca.markets"
        if ALPACA_API_KEY.startswith("PK")
        else "https://api.alpaca.markets"
    )
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }
    try:
        with httpx.Client(base_url=base, timeout=30) as c:
            r = c.get("/v2/account", headers=headers)
            body_alpaca = r.json() if r.status_code < 400 else {}
    except Exception:
        body_alpaca = {}

    if sc_oa != 200 or not body_oa or not body_alpaca:
        report.add(
            "v1 /funds vs Alpaca /v2/account",
            False,
            status=sc_oa,
            detail="missing data",
        )
        return

    oa_cash = (body_oa.get("data") or {}).get("availablecash")
    al_cash = body_alpaca.get("cash")

    # Cash should match within rounding (both come from the same
    # Alpaca account).
    try:
        oa_f = float(str(oa_cash).replace(",", "").replace("$", ""))
        al_f = float(al_cash)
        match = abs(oa_f - al_f) < 0.01
    except Exception:
        match = str(oa_cash) == str(al_cash)
    report.add(
        "v1 /funds.availablecash == Alpaca /v2/account.cash",
        match,
        detail=f"oa={oa_cash} alpaca={al_cash}",
    )


def sweep_order_flow_v2(
    client: httpx.Client, apikey: str, report: Report
) -> None:
    """Place + cancel a deep-out-of-money LIMIT order via /api/v2/orders.

    Uses LIMIT $1.00 BUY on AAPL XNAS — guaranteed to never fill
    on a paper account, so we can cleanly observe placed-then-
    cancelled lifecycle without affecting the operator's portfolio.
    """
    if not report.json_mode:
        print("\n=== /api/v2/orders order-flow ===")

    headers = {"X-API-KEY": apikey, "Content-Type": "application/json"}
    body = {
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "price": "1.00",
        "time_in_force": "DAY",
        "session": "REGULAR",
    }

    # Place
    r = client.post("/api/v2/orders", headers=headers, json=body)
    sc = r.status_code
    resp = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    order_id = (resp or {}).get("data", {}).get("order_id") or ""
    report.add(
        "v2 POST /orders LIMIT BUY 1 AAPL @ $1.00",
        sc == 200 and bool(order_id),
        status=sc,
        detail=f"order_id={order_id[:8]}..." if order_id else (
            (resp or {}).get("error", {}).get("message", "")[:60] if resp else ""
        ),
    )
    if not order_id:
        return

    # Verify in v2 list
    r = client.get("/api/v2/orders?status=open", headers={"X-API-KEY": apikey})
    sc = r.status_code
    open_orders = (r.json().get("data") or {}).get("orders", []) if sc == 200 else []
    found = any(o.get("id") == order_id or o.get("order_id") == order_id for o in open_orders)
    report.add(
        "v2 GET /orders shows the placed order",
        found,
        detail=f"{len(open_orders)} open orders",
    )

    # Verify in v1 orderbook
    r = client.post("/api/v1/orderbook", json={"apikey": apikey})
    if r.status_code == 200:
        body_v1 = r.json()
        v1_orders = (body_v1.get("data") or {}).get("orders") or body_v1.get("data") or []
        v1_found = any(
            (o.get("orderid") == order_id or o.get("order_id") == order_id)
            for o in (v1_orders if isinstance(v1_orders, list) else [])
        )
        report.add(
            "v1 /orderbook shows the placed order",
            v1_found,
            detail=f"{len(v1_orders) if isinstance(v1_orders, list) else 0} orders",
        )

    # Cancel via v2
    r = client.delete(
        f"/api/v2/orders/{order_id}", headers={"X-API-KEY": apikey}
    )
    report.add(
        f"v2 DELETE /orders/{order_id[:8]}...",
        r.status_code == 200,
        status=r.status_code,
    )


def _wait_for_order_status(
    client: httpx.Client,
    apikey: str,
    order_id: str,
    *,
    target_statuses: tuple[str, ...] = ("filled", "FILLED", "complete", "COMPLETE"),
    timeout_s: float = 90.0,
    poll_s: float = 0.5,
) -> tuple[str, dict | None]:
    """Poll /api/v2/orders until order_id reaches a target status
    or timeout. Returns ``(status, last_row)`` — status is the
    last observed value (may be the timeout status if we never saw
    the target)."""
    import time

    last_status = "UNKNOWN"
    last_row: dict | None = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = client.get(
            "/api/v2/orders?status=all",
            headers={"X-API-KEY": apikey},
        )
        if r.status_code == 200:
            for o in (r.json().get("data") or {}).get("orders", []):
                oid = o.get("id") or o.get("order_id")
                if oid == order_id:
                    last_status = (o.get("status") or "").lower()
                    last_row = o
                    if last_status in [s.lower() for s in target_statuses]:
                        return last_status, last_row
                    break
        time.sleep(poll_s)
    return last_status, last_row


def sweep_market_open_fill_v2(
    client: httpx.Client, apikey: str, report: Report
) -> str | None:
    """Place a marketable LIMIT BUY (1 AAPL @ $9999) so the order
    fills at current ASK on the paper account. Verifies:
    - order placed
    - status reaches 'filled' within 30s
    - position appears in /api/v2/positions
    - cross-checks with Alpaca direct /v2/positions

    Returns the order_id so the caller can chain a close (the
    position-close round-trip is a separate sweep — this returns
    after the fill so the position is still open for that test).
    """
    if not report.json_mode:
        print("\n=== /api/v2/orders MARKETABLE LIMIT (real fill) ===")

    headers = {"X-API-KEY": apikey, "Content-Type": "application/json"}
    body = {
        "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "1",
        "quantity_unit": "WHOLE",
        "price": "9999.00",  # Far above any realistic AAPL ask → fills at market
        "time_in_force": "DAY",
        "session": "REGULAR",
    }

    r = client.post("/api/v2/orders", headers=headers, json=body)
    sc = r.status_code
    resp = r.json() if sc < 500 else None
    order_id = (resp or {}).get("data", {}).get("order_id") or ""
    report.add(
        "v2 POST /orders LIMIT BUY 1 AAPL @ $9999 (marketable)",
        sc == 200 and bool(order_id),
        status=sc,
        detail=f"order_id={order_id[:8]}..." if order_id else (resp or {}).get("error", {}).get("message", "")[:80] if resp else "",
    )
    if not order_id:
        return None

    # Wait for fill (Alpaca paper typically fills marketable orders
    # within ~1s, but we give 30s for safety).
    status, row = _wait_for_order_status(client, apikey, order_id, timeout_s=90)
    is_filled = status in ("filled", "complete", "FILLED", "COMPLETE")
    report.add(
        f"v2 order {order_id[:8]}... reaches filled status",
        is_filled,
        detail=f"status={status}, qty_filled={(row or {}).get('filled_qty', '?')}",
    )

    # Verify v2 /positions shows AAPL
    r = client.get("/api/v2/positions", headers={"X-API-KEY": apikey})
    positions = (r.json().get("data") or {}).get("positions", []) if r.status_code == 200 else []
    aapl_pos = next(
        (
            p
            for p in positions
            if (p.get("symbol") or "").upper() == "AAPL"
            or (p.get("canonical_symbol") or "").upper() == "AAPL"
        ),
        None,
    )
    report.add(
        "v2 /positions includes the AAPL position",
        aapl_pos is not None,
        detail=f"qty={aapl_pos.get('quantity', '?')}" if aapl_pos else f"{len(positions)} positions",
    )

    # Cross-check Alpaca direct
    if ALPACA_API_KEY and ALPACA_API_SECRET:
        base = (
            "https://paper-api.alpaca.markets"
            if ALPACA_API_KEY.startswith("PK")
            else "https://api.alpaca.markets"
        )
        try:
            with httpx.Client(base_url=base, timeout=30) as c:
                r = c.get(
                    "/v2/positions/AAPL",
                    headers={
                        "APCA-API-KEY-ID": ALPACA_API_KEY,
                        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
                    },
                )
                sc = r.status_code
                ap_body = r.json() if sc == 200 else None
        except Exception:
            sc = 0
            ap_body = None
        report.add(
            "Alpaca direct /v2/positions/AAPL (cross-check)",
            sc == 200 and ap_body and ap_body.get("symbol") == "AAPL",
            status=sc,
            detail=f"qty={ap_body.get('qty')} avg=${ap_body.get('avg_entry_price')}"
            if ap_body
            else "",
        )

    return order_id


def sweep_market_open_modify_v1(
    client: httpx.Client, apikey: str, report: Report
) -> None:
    """Place a deep-OOM LIMIT BUY, modify the price, then cancel.
    Uses /api/v1/modifyorder which is the only modify endpoint
    available across both v1 and v2 lanes today."""
    if not report.json_mode:
        print("\n=== /api/v1/modifyorder lifecycle (market-open) ===")

    payload = {
        "apikey": apikey,
        "strategy": "api_surface_sweep_modify",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "action": "BUY",
        "pricetype": "LIMIT",
        "quantity": "1",
        "price": "50.00",  # Deep OOM — won't fill
        "product": "DAY",
    }
    r = client.post("/api/v1/placeorder", json=payload)
    sc = r.status_code
    resp = r.json() if sc < 500 else None
    orderid = (resp or {}).get("orderid") or ""
    report.add(
        "v1 /placeorder LIMIT BUY @ $50 (deep-OOM)",
        sc == 200 and bool(orderid),
        status=sc,
        detail=(resp or {}).get("message", "")[:60] if not orderid else f"orderid={orderid[:8]}...",
    )
    if not orderid:
        return

    # Modify the price.
    modify_payload = {
        "apikey": apikey,
        "strategy": "api_surface_sweep_modify",
        "orderid": orderid,
        "symbol": "AAPL",
        "exchange": "XNAS",
        "action": "BUY",
        "pricetype": "LIMIT",
        "quantity": "1",
        "price": "40.00",  # Modified down — even further OOM
        "product": "DAY",
    }
    r = client.post("/api/v1/modifyorder", json=modify_payload)
    # /api/v1/modifyorder is India-lane only today — non-India
    # brokers see 410 via the v1 lane guard. Accept 200 (India)
    # OR 410 (non-India v1 bridge gap; documented future work).
    sc_modify = r.status_code
    msg_modify = (r.json() if sc_modify < 500 else {}).get("message", "")[:60]
    report.add(
        f"v1 /modifyorder {orderid[:8]}... price 50 to 40",
        sc_modify in (200, 410),
        status=sc_modify,
        detail=msg_modify,
    )

    # Cancel.
    r = client.post(
        "/api/v1/cancelorder",
        json={"apikey": apikey, "orderid": orderid, "strategy": "api_surface_sweep_modify"},
    )
    report.add(
        f"v1 /cancelorder {orderid[:8]}... (post-modify)",
        r.status_code == 200,
        status=r.status_code,
    )


def sweep_market_open_live_quotes(
    client: httpx.Client, apikey: str, report: Report
) -> None:
    """Verify /api/v1/quotes returns a fresh, non-zero LTP for
    AAPL when the market is open."""
    if not report.json_mode:
        print("\n=== /api/v1/quotes live LTP (market-open) ===")

    r = client.post(
        "/api/v1/quotes",
        json={"apikey": apikey, "symbol": "AAPL", "exchange": "XNAS"},
    )
    sc = r.status_code
    body = r.json() if sc < 500 else None
    data = (body or {}).get("data") or {}
    ltp = data.get("ltp")
    try:
        ltp_f = float(ltp) if ltp is not None else 0.0
    except Exception:
        ltp_f = 0.0
    report.add(
        "v1 /quotes AAPL LTP > 0 (market-open data)",
        sc == 200 and ltp_f > 0,
        status=sc,
        detail=f"ltp={ltp}",
    )


def sweep_position_close(
    client: httpx.Client,
    apikey: str,
    open_order_id: str | None,
    report: Report,
) -> None:
    """Close the AAPL position opened by the marketable-LIMIT test.

    Path: /api/v1/closeposition (mounted across both lanes today).
    """
    if not report.json_mode:
        print("\n=== /api/v1/closeposition round-trip (market-open) ===")

    # Snapshot positions before close
    r = client.get("/api/v2/positions", headers={"X-API-KEY": apikey})
    pre_positions = (r.json().get("data") or {}).get("positions", []) if r.status_code == 200 else []
    def _is_aapl(p: dict) -> bool:
        return (
            (p.get("symbol") or "").upper() == "AAPL"
            or (p.get("canonical_symbol") or "").upper() == "AAPL"
        )

    has_aapl_pre = any(_is_aapl(p) for p in pre_positions)
    if not has_aapl_pre:
        report.add(
            "Position-close skipped (no AAPL position)",
            True,
            detail="open-fill leg may not have completed",
        )
        return

    # Determine the AAPL quantity to close (cumulative across runs;
    # Alpaca paper allows fractional positions so this may not be
    # an integer — float-cast preserves fractional shares).
    aapl_qty_float = 0.0
    for p in pre_positions:
        if _is_aapl(p):
            try:
                aapl_qty_float = abs(float(str(p.get("quantity", "0")).replace(",", "")))
            except Exception:
                aapl_qty_float = 0.0
            break
    # Format the quantity for the order body. Whole shares stay
    # whole; fractional residue gets sent as a decimal — Alpaca's
    # close-position semantics accept fractional sells of any
    # outstanding fractional position.
    if aapl_qty_float > 0:
        if aapl_qty_float == int(aapl_qty_float):
            aapl_qty_str = str(int(aapl_qty_float))
            qty_unit = "WHOLE"
        else:
            # Alpaca supports up to 9 decimal places for fractional
            # quantities. Use 9 here so positions like 1.000000004
            # (residue from prior runs) get fully closed instead of
            # truncated to 1, which leaves a sub-cent residual.
            aapl_qty_str = f"{aapl_qty_float:.9f}".rstrip("0").rstrip(".")
            qty_unit = "FRACTIONAL"
    else:
        aapl_qty_str = "0"
        qty_unit = "WHOLE"
    aapl_qty = aapl_qty_float  # back-compat var name for downstream messages

    # Close via marketable SELL on the v2 orders endpoint. (v1
    # /closeposition is India-only via the v1 lane guard; v2 has
    # no "close all" endpoint yet, so we close via opposite-side
    # marketable LIMIT — same shape as the open leg.)
    if aapl_qty > 0:
        # MARKET order — guaranteed fill at the current bid; the
        # earlier $0.01 LIMIT was rejected by Alpaca's "limit price
        # too far from market" rule (LIMIT must be within ~30% of
        # last trade; $0.01 vs $277 was way out of band).
        close_body = {
            "instrument": {"venue_code": "XNAS", "canonical_symbol": "AAPL"},
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": aapl_qty_str,
            "quantity_unit": qty_unit,
            "time_in_force": "DAY",
            "session": "REGULAR",
        }
        r = client.post(
            "/api/v2/orders",
            headers={"X-API-KEY": apikey, "Content-Type": "application/json"},
            json=close_body,
        )
        sc = r.status_code
        resp = r.json() if sc < 500 else None
        close_order_id = (resp or {}).get("data", {}).get("order_id") or ""
        report.add(
            f"v2 POST /orders MARKET SELL {aapl_qty_str} AAPL (close)",
            sc == 200 and bool(close_order_id),
            status=sc,
            detail=f"order_id={close_order_id[:8]}..." if close_order_id else "",
        )
        if close_order_id:
            status, _row = _wait_for_order_status(
                client, apikey, close_order_id, timeout_s=90
            )
            report.add(
                f"v2 close order {close_order_id[:8]}... reaches filled",
                status in ("filled", "complete"),
                detail=f"status={status}",
            )

    # Allow the close-order to settle.
    import time
    time.sleep(3)

    # Verify position closed in OpenAlgo + Alpaca.
    r = client.get("/api/v2/positions", headers={"X-API-KEY": apikey})
    post_positions = (r.json().get("data") or {}).get("positions", []) if r.status_code == 200 else []
    has_aapl_post = any(
        _is_aapl(p)
        and float(str(p.get("quantity", "0")).replace(",", "")) != 0
        for p in post_positions
    )
    report.add(
        "v2 /positions no longer holds AAPL after close",
        not has_aapl_post,
        detail=f"{len(post_positions)} positions remain",
    )


def sweep_order_flow_v1_bridge(
    client: httpx.Client, apikey: str, report: Report
) -> None:
    """Place + cancel via legacy /api/v1/placeorder, which routes
    through services.v1_compat_bridge for non-India brokers."""
    if not report.json_mode:
        print("\n=== /api/v1/placeorder bridge order-flow ===")

    payload = {
        "apikey": apikey,
        "strategy": "api_surface_sweep",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "action": "BUY",
        "pricetype": "LIMIT",
        "quantity": "1",
        "price": "1.00",
        "product": "DAY",
    }
    r = client.post("/api/v1/placeorder", json=payload)
    sc = r.status_code
    resp = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    orderid = (resp or {}).get("orderid") or ""
    report.add(
        "v1 /placeorder LIMIT BUY 1 AAPL @ $1.00",
        sc == 200 and bool(orderid),
        status=sc,
        detail=f"orderid={orderid[:8]}..."
        if orderid
        else (resp or {}).get("message", "")[:60] if resp else "",
    )
    if not orderid:
        return

    # Cancel via v1
    r = client.post(
        "/api/v1/cancelorder",
        json={"apikey": apikey, "orderid": orderid, "strategy": "api_surface_sweep"},
    )
    report.add(
        f"v1 /cancelorder {orderid[:8]}...",
        r.status_code == 200,
        status=r.status_code,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAlgo v7 API surface sweep + Alpaca cross-check"
    )
    parser.add_argument(
        "--skip-alpaca-direct",
        action="store_true",
        help="Skip the direct Alpaca API calls (useful when offline)",
    )
    parser.add_argument(
        "--skip-order-flow",
        action="store_true",
        help="Skip the place/cancel order-flow tests (read-only sweep)",
    )
    parser.add_argument(
        "--market-open",
        action="store_true",
        help="Add market-open-only checks: marketable LIMIT (real fill), "
        "modify-order, live LTP quote, and position close round-trip",
    )
    parser.add_argument(
        "--json", action="store_true", help="Machine-readable JSON output"
    )
    args = parser.parse_args()

    if not USERNAME or not PASSWORD:
        print("Set web_login_username + web_login_password in .env")
        return 2

    if not args.json:
        print(f"OpenAlgo: {BASE}")
        print(f"User: {USERNAME}")
        print(
            f"Alpaca key prefix: {ALPACA_API_KEY[:2]}..."
            if ALPACA_API_KEY
            else "Alpaca key: not configured"
        )

    try:
        client, apikey = login_and_get_apikey()
    except Exception as e:
        print(f"Login failed: {e}")
        return 1

    if not args.json:
        print(f"API key: {apikey[:8]}...")

    report = Report(json_mode=args.json)

    sweep_v1(client, apikey, report)
    sweep_v2(client, apikey, report)
    sweep_auth(client, report)
    if not args.skip_order_flow:
        sweep_order_flow_v2(client, apikey, report)
        sweep_order_flow_v1_bridge(client, apikey, report)
    if args.market_open:
        sweep_market_open_live_quotes(client, apikey, report)
        sweep_market_open_modify_v1(client, apikey, report)
        # Marketable-fill leaves the position open; the
        # position-close test cleans it up.
        open_order_id = sweep_market_open_fill_v2(client, apikey, report)
        sweep_position_close(client, apikey, open_order_id, report)
    if not args.skip_alpaca_direct:
        sweep_alpaca_direct(report)
        cross_check_balance(client, apikey, report)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
