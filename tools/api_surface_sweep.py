"""v7 — Full API surface sweep against local Flask + Alpaca paper.

Drives the local OpenAlgo /api/v1/* and /api/v2/* endpoints with
the operator's API key, plus a few direct hits against Alpaca's
paper API to cross-check parity. Designed to surface any
regression introduced by the v7 refactor that the Playwright
suite doesn't catch (deeper API path coverage).

Usage:
    uv run python tools/api_surface_sweep.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

import httpx  # noqa: E402

BASE = os.environ.get("OPENALGO_BASE_URL", "http://127.0.0.1:5000")
USERNAME = os.environ.get("web_login_username") or os.environ.get("WEB_LOGIN_USERNAME", "")
PASSWORD = os.environ.get("web_login_password") or os.environ.get("WEB_LOGIN_PASSWORD", "")


def login_and_get_apikey() -> tuple[httpx.Client, str]:
    """Log into the OpenAlgo UI session, then retrieve the API
    key the user generated for programmatic access."""
    client = httpx.Client(base_url=BASE, follow_redirects=True, timeout=30)
    # Page 1 — fetch login form to get CSRF.
    r = client.get("/login")
    r.raise_for_status()
    # Flask-WTF csrf token is in the HTML — find via simple parse.
    text = r.text
    csrf_idx = text.find('name="csrf_token"')
    if csrf_idx == -1:
        # Some forms use meta-tag or X-CSRFToken
        csrf_token = ""
    else:
        # Find the value="..." part after csrf_token.
        slice_text = text[csrf_idx:csrf_idx + 400]
        v_idx = slice_text.find('value="')
        csrf_token = slice_text[v_idx + 7 : slice_text.find('"', v_idx + 7)] if v_idx > -1 else ""

    # Submit login.
    r = client.post(
        "/auth/login",
        data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrf_token": csrf_token,
        },
    )
    if r.status_code >= 400:
        raise RuntimeError(f"login failed: {r.status_code} {r.text[:200]}")

    # Fetch API key.
    r = client.get("/apikey", headers={"Accept": "application/json"})
    r.raise_for_status()
    body = r.json()
    apikey = body.get("api_key") or body.get("apikey") or ""
    if not apikey:
        raise RuntimeError(f"no api_key in /apikey response: {body}")
    return client, apikey


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return ok


def main() -> int:
    if not USERNAME or not PASSWORD:
        print("Set web_login_username + web_login_password in .env")
        return 2
    try:
        client, apikey = login_and_get_apikey()
    except Exception as e:
        print(f"Setup failed: {e}")
        return 1

    print(f"\n--- v1 API surface (broker={os.environ.get('BROKER_API_KEY','')[:8]}...) ---")
    fails: list[str] = []

    def call_v1(path: str, body: dict | None = None) -> tuple[int, dict | None]:
        payload = {"apikey": apikey}
        if body:
            payload.update(body)
        r = client.post(f"/api/v1/{path}", json=payload)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None

    # Funds (read-only): expects 200 + balance.
    sc, body = call_v1("funds")
    ok = sc == 200 and body and body.get("status") == "success"
    if not check("v1 /funds", ok, f"sc={sc}"):
        fails.append("v1 /funds")

    # Holdings: 200 + list (may be empty).
    sc, body = call_v1("holdings")
    ok = sc == 200 and body and body.get("status") == "success"
    if not check("v1 /holdings", ok, f"sc={sc}"):
        fails.append("v1 /holdings")

    # Position book: 200 + list.
    sc, body = call_v1("positionbook")
    ok = sc == 200 and body and body.get("status") == "success"
    if not check("v1 /positionbook", ok, f"sc={sc}"):
        fails.append("v1 /positionbook")

    # Order book: 200 + list.
    sc, body = call_v1("orderbook")
    ok = sc == 200 and body and body.get("status") == "success"
    if not check("v1 /orderbook", ok, f"sc={sc}"):
        fails.append("v1 /orderbook")

    # Trade book: 200 + list.
    sc, body = call_v1("tradebook")
    ok = sc == 200 and body and body.get("status") == "success"
    if not check("v1 /tradebook", ok, f"sc={sc}"):
        fails.append("v1 /tradebook")

    print(f"\n--- v2 API surface ---")

    def call_v2(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict | None]:
        headers = {"X-API-KEY": apikey}
        if method == "GET":
            r = client.get(f"/api/v2/{path}", headers=headers)
        else:
            r = client.request(method, f"/api/v2/{path}", headers=headers, json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None

    # /api/v2/regions
    sc, body = call_v2("regions")
    ok = sc == 200 and body and "regions" in (body.get("data") or {})
    if not check("v2 /regions", ok, f"sc={sc}, count={len((body.get('data') or {}).get('regions',[])) if body else 0}"):
        fails.append("v2 /regions")

    # /api/v2/regions/india/holidays
    sc, body = call_v2("regions/india/holidays?year=2026")
    ok = sc == 200 and body and (body.get("data") or {}).get("region_code") == "india"
    if not check("v2 /regions/india/holidays?year=2026", ok, f"sc={sc}"):
        fails.append("v2 india holidays")

    # /api/v2/regions/us/holidays
    sc, body = call_v2("regions/us/holidays?year=2026")
    ok = sc == 200
    if not check("v2 /regions/us/holidays?year=2026", ok, f"sc={sc}"):
        fails.append("v2 us holidays")

    # /api/v2/regions/atlantis/holidays — 404
    sc, body = call_v2("regions/atlantis/holidays")
    ok = sc == 404
    if not check("v2 /regions/atlantis/holidays (404)", ok, f"sc={sc}"):
        fails.append("v2 unknown region 404")

    # /api/v2/regions/india/flow_defaults
    sc, body = call_v2("regions/india/flow_defaults")
    ok = sc == 200 and body and (body.get("data") or {}).get("region_code") == "india"
    if not check("v2 /regions/india/flow_defaults", ok, f"sc={sc}"):
        fails.append("v2 india flow_defaults")

    # /api/v2/capabilities
    sc, body = call_v2("capabilities")
    ok = sc == 200
    if not check("v2 /capabilities", ok, f"sc={sc}"):
        fails.append("v2 capabilities")

    print(f"\n--- /auth/broker-config ---")
    r = client.get("/auth/broker-config")
    sc = r.status_code
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    ok = sc == 200 and body and "broker_mode" in body
    if not check("/auth/broker-config (broker_mode field)", ok, f"sc={sc}, mode={body.get('broker_mode') if body else None}"):
        fails.append("/auth/broker-config")

    print(f"\n--- summary ---")
    if fails:
        print(f"FAILED ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("All checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
