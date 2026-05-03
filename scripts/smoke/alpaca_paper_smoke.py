"""Alpaca paper-API connectivity smoke (read-only).

Hits ``GET /v2/account`` with the credentials resolved by
``broker.alpaca.api.auth_api.authenticate``. Confirms the keys work
end-to-end against ``paper-api.alpaca.markets`` (or the live endpoint
when ``ALPACA_LIVE_MODE=1``).

Run::

    uv run python scripts/smoke/alpaca_paper_smoke.py

The script never places an order — it is purely a read-side ping.
Exits 0 on success, 1 on any failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path so ``broker.alpaca.*``
# imports resolve when the script is run from any cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
from dotenv import load_dotenv

# Load .env so the smoke runs the same way the Flask app does.
# Override existing shell env vars so the operator's .env config
# wins; the goal of this script is to validate the .env contents.
load_dotenv(_REPO_ROOT / ".env", override=True)

from broker.alpaca.api.auth_api import authenticate  # noqa: E402


def main() -> int:
    try:
        auth = authenticate()
    except ValueError as exc:
        print(f"[FAIL] credential resolution: {exc}")
        return 1

    mode_label = "PAPER" if auth.is_paper else "LIVE"
    print(f"Mode:       {mode_label}")
    print(f"Base URL:   {auth.base_url}")
    print(f"Key prefix: {auth.headers.get('APCA-API-KEY-ID', '')[:6]}...")
    print()

    try:
        with httpx.Client(
            base_url=auth.base_url,
            headers=dict(auth.headers),
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            resp = client.get("/v2/account")
    except httpx.HTTPError as exc:
        print(f"[FAIL] network: {exc}")
        return 1

    if resp.status_code == 401:
        print("[FAIL] 401 Unauthorized — check the API key + secret.")
        return 1
    if resp.status_code == 403:
        print("[FAIL] 403 Forbidden — key valid but lacks permissions.")
        return 1
    if resp.status_code >= 400:
        print(f"[FAIL] HTTP {resp.status_code}: {resp.text}")
        return 1

    body = resp.json()
    interesting = (
        "id",
        "account_number",
        "status",
        "currency",
        "cash",
        "buying_power",
        "equity",
        "portfolio_value",
        "pattern_day_trader",
        "trading_blocked",
        "transfers_blocked",
        "account_blocked",
    )
    print("/v2/account response (selected fields):")
    print(json.dumps({k: body.get(k) for k in interesting}, indent=2))

    blocked = any(body.get(k) for k in ("trading_blocked", "transfers_blocked", "account_blocked"))
    if blocked:
        print("\n[WARN] account has at least one block flag set.")
    else:
        print("\n[OK] account is active and not blocked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
