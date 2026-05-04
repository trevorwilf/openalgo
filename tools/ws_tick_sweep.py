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


async def run_sweep(symbols: list[dict], mode: str, timeout: float) -> int:
    """Connect, authenticate, subscribe to all ``symbols``, wait
    for at least one tick per symbol within ``timeout`` seconds.
    Single-symbol caller passes a 1-element list."""
    apikey = fetch_apikey()
    print(f"apikey: {apikey[:8]}...")
    sym_keys = {(s["symbol"], s["exchange"]) for s in symbols}
    print(f"connecting to {WS_URL} (subscribing to {len(symbols)}) ...")
    try:
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({"action": "authenticate", "api_key": apikey}))
            auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            print(f"auth response: {auth_resp.get('status')} / {auth_resp.get('message', '')}")
            if auth_resp.get("status") not in ("success", "ok", "authenticated"):
                return 1

            for s in symbols:
                await ws.send(
                    json.dumps(
                        {
                            "action": "subscribe",
                            "symbol": s["symbol"],
                            "exchange": s["exchange"],
                            "mode": mode,
                        }
                    )
                )
                sub_resp = await asyncio.wait_for(ws.recv(), timeout=10)
                body = json.loads(sub_resp)
                statuses = (body.get("subscriptions") or [{}])[0].get("status", "?")
                print(f"  subscribe {s['symbol']}@{s['exchange']}: {statuses}")

            seen: dict[tuple[str, str], int] = {}
            tick_total = 0
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        msg = await ws.recv()
                        body = json.loads(msg)
                        if body.get("type") in (
                            "live", "market_data", "ltp", "quote", "depth"
                        ) or ("data" in body and not body.get("status")):
                            tick_total += 1
                            sym = body.get("symbol") or (body.get("data") or {}).get("symbol")
                            exc = body.get("exchange") or (body.get("data") or {}).get("exchange")
                            key = (sym, exc)
                            seen[key] = seen.get(key, 0) + 1
                            if all(k in seen for k in sym_keys):
                                break
            except (asyncio.TimeoutError, TimeoutError):
                pass

            for s in symbols:
                await ws.send(
                    json.dumps(
                        {
                            "action": "unsubscribe",
                            "symbol": s["symbol"],
                            "exchange": s["exchange"],
                            "mode": mode,
                        }
                    )
                )

            print(f"\n=== Result ===")
            print(f"total ticks: {tick_total}")
            for s in symbols:
                k = (s["symbol"], s["exchange"])
                count = seen.get(k, 0)
                mark = "OK  " if count > 0 else "FAIL"
                print(f"  [{mark}] {s['symbol']}@{s['exchange']}: {count} ticks")
            if all(seen.get((s["symbol"], s["exchange"]), 0) > 0 for s in symbols):
                print("PASS")
                return 0
            print("FAIL: at least one symbol got no ticks")
            return 1

    except Exception as e:
        print(f"WebSocket error: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAlgo WebSocket tick verification"
    )
    parser.add_argument(
        "--symbols",
        default="AAPL@XNAS",
        help="Comma-separated SYMBOL@EXCHANGE pairs, e.g. "
        "'AAPL@XNAS,MSFT@XNAS,SPY@ARCX'",
    )
    parser.add_argument(
        "--symbol",
        help="(legacy) single-symbol form, paired with --exchange",
    )
    parser.add_argument("--exchange", default="XNAS")
    parser.add_argument("--mode", default="LTP", choices=["LTP", "Quote", "Depth"])
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    if not USERNAME or not PASSWORD:
        print("set web_login_username + web_login_password in .env")
        return 2

    if args.symbol:
        syms = [{"symbol": args.symbol, "exchange": args.exchange}]
    else:
        syms = []
        for pair in args.symbols.split(","):
            if "@" not in pair:
                continue
            symbol, exchange = pair.strip().split("@", 1)
            syms.append({"symbol": symbol.strip(), "exchange": exchange.strip()})

    return asyncio.run(run_sweep(syms, args.mode, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
