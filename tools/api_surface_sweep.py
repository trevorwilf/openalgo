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
    if not args.skip_alpaca_direct:
        sweep_alpaca_direct(report)
        cross_check_balance(client, apikey, report)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
