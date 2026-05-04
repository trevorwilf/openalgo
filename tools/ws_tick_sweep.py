"""v7 — WebSocket market-data tick verification.

Connects to ws://127.0.0.1:8765, authenticates with the
operator's apikey, subscribes to AAPL@XNAS, and verifies real
ticks flow within a configurable window.

End-to-end coverage:
- WebSocket handshake to the unified proxy
- ``authenticate`` action (verifies the apikey path)
- ``subscribe`` action (verifies the broker adapter is wired)
- At least one tick message received within the window

Usage:
    uv run python tools/ws_tick_sweep.py
    uv run python tools/ws_tick_sweep.py --timeout 30 --symbol AAPL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=True)

import httpx  # noqa: E402

import websockets  # noqa: E402

OPENALGO_BASE = os.environ.get("OPENALGO_BASE_URL", "http://127.0.0.1:5000")
WS_URL = os.environ.get("OPENALGO_WS_URL", "ws://127.0.0.1:8765")
USERNAME = (os.environ.get("web_login_username") or "").strip().strip("'\"")
PASSWORD = (os.environ.get("web_login_password") or "").strip().strip("'\"")


def fetch_apikey() -> str:
    client = httpx.Client(base_url=OPENALGO_BASE, follow_redirects=False, timeout=30)
    csrf = client.get("/auth/csrf-token").json()["csrf_token"]
    r = client.post(
        "/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"X-CSRFToken": csrf},
    )
    r.raise_for_status()
    body = client.get("/apikey", headers={"Accept": "application/json"}).json()
    return body.get("api_key") or body.get("apikey") or ""


async def run_sweep(symbol: str, exchange: str, mode: str, timeout: float) -> int:
    apikey = fetch_apikey()
    print(f"apikey: {apikey[:8]}...")

    print(f"connecting to {WS_URL} ...")
    try:
        async with websockets.connect(WS_URL) as ws:
            # Authenticate.
            await ws.send(json.dumps({"action": "authenticate", "api_key": apikey}))
            auth_resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            auth_resp = json.loads(auth_resp_raw)
            print(f"auth response: {auth_resp.get('status')} / {auth_resp.get('message', '')}")
            if auth_resp.get("status") not in ("success", "ok", "authenticated"):
                print(f"  full body: {auth_resp_raw[:200]}")
                return 1

            # Subscribe.
            await ws.send(
                json.dumps(
                    {
                        "action": "subscribe",
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                    }
                )
            )
            sub_resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"subscribe response: {sub_resp_raw[:200]}")

            # Wait for at least one tick.
            tick_count = 0
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        msg = await ws.recv()
                        body = json.loads(msg)
                        # Ticks come as ``{"data": {...}, "type": "live", ...}``
                        # or similar — anything that's not just a status
                        # response counts.
                        is_tick = (
                            body.get("type") in ("live", "market_data", "ltp", "quote", "depth")
                            or "data" in body
                            and not body.get("status")
                        )
                        if is_tick:
                            tick_count += 1
                            print(f"  tick #{tick_count}: {str(body)[:120]}...")
                            if tick_count >= 3:
                                break
            except (asyncio.TimeoutError, TimeoutError):
                pass

            await ws.send(
                json.dumps(
                    {
                        "action": "unsubscribe",
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                    }
                )
            )
            print(f"\n=== Result ===")
            print(f"ticks received: {tick_count}")
            if tick_count > 0:
                print("PASS")
                return 0
            print("FAIL: no ticks received within window")
            return 1

    except Exception as e:
        print(f"WebSocket error: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAlgo WebSocket tick verification"
    )
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--exchange", default="XNAS")
    parser.add_argument("--mode", default="LTP", choices=["LTP", "Quote", "Depth"])
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    if not USERNAME or not PASSWORD:
        print("set web_login_username + web_login_password in .env")
        return 2

    return asyncio.run(run_sweep(args.symbol, args.exchange, args.mode, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
