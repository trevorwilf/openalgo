#!/usr/bin/env python3
"""Bowaka v2 — OpenAlgo /api/v2 HTTP client.

Reusable thin wrappers around the OpenAlgo endpoints v1 already
talked to: ``/api/v2/balances``, ``/api/v2/quotes``, ``/api/v2/bars``,
``/api/v2/orders``. The v2 universe builder, scanner, and strategy
all use this module so live network behavior is consistent across
the stack.

Pure HTTP plumbing — no v2-specific business logic here. Tests can
substitute an ``httpx.MockTransport`` via the ``transport`` kwarg
in ``make_http_client``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd


LOG = logging.getLogger("bowaka_v2_openalgo_client")


def resolve_host_and_key() -> tuple[str, str]:
    """Read HOST_SERVER + OPENALGO_API_KEY from env. The same env
    vars v1 used."""
    host = os.environ.get("HOST_SERVER", "http://127.0.0.1:5000")
    api_key = os.environ.get("OPENALGO_API_KEY")
    if not api_key:
        raise RuntimeError("OPENALGO_API_KEY must be set in environment")
    return host, api_key


def make_http_client(
    base_url: str,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    kwargs: dict[str, Any] = {"base_url": base_url, "timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


def _api_headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------- equity / balances


def fetch_equity(http: httpx.Client, api_key: str) -> float:
    r = http.get("/api/v2/balances", headers=_api_headers(api_key))
    r.raise_for_status()
    body = r.json().get("data") or {}
    bal = body.get("balance") or body.get("balances") or {}
    if isinstance(bal, dict):
        if "equity" in bal and bal["equity"] is not None:
            return float(bal["equity"])
        if "cash" in bal and bal["cash"] is not None:
            return float(bal["cash"])
    raise RuntimeError(
        f"could not parse equity from /api/v2/balances: {body!r}"
    )


# ---------------------------------------------------------------- bars


def fetch_bars(
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """POST /api/v2/bars for one (symbol, interval) over [start, end).

    ``interval`` is ``"1m"`` / ``"1d"`` etc. Returns an
    ascending-by-timestamp DataFrame with ``timestamp`` + standard
    OHLCV columns. Empty frame on no bars / 4xx — never raises on
    HTTP failure (callers treat as "skip this symbol").
    """
    body = {
        "apikey": api_key,
        "instrument": {
            "venue_code": venue_code,
            "canonical_symbol": symbol,
        },
        "interval": interval,
        "start": start.astimezone(timezone.utc).isoformat(),
        "end":   end.astimezone(timezone.utc).isoformat(),
    }
    try:
        r = http.post("/api/v2/bars", json=body,
                       headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.debug("bars fetch network error for %s: %s", symbol, e)
        return pd.DataFrame()
    if r.status_code != 200:
        LOG.debug(
            "bars fetch %d for %s: %s",
            r.status_code, symbol, (r.text or "")[:200],
        )
        return pd.DataFrame()
    payload = r.json().get("data") or {}
    rows = payload.get("bars") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ts" in df.columns:
        df["timestamp"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
        df = df.drop(columns=["ts"])
    elif "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------- quotes


def fetch_quote(
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    symbol: str,
) -> dict | None:
    """POST /api/v2/quotes for one instrument. Returns the quote
    dict or None on failure."""
    body = {
        "apikey": api_key,
        "instruments": [{
            "venue_code": venue_code,
            "canonical_symbol": symbol,
        }],
    }
    try:
        r = http.post("/api/v2/quotes", json=body,
                       headers=_api_headers(api_key))
    except httpx.HTTPError as e:
        LOG.warning("quote fetch failed for %s: %s", symbol, e)
        return None
    if r.status_code != 200:
        LOG.warning(
            "quote fetch %d for %s: %s",
            r.status_code, symbol, (r.text or "")[:200],
        )
        return None
    rows = (r.json().get("data") or [])
    if not rows:
        return None
    q = (rows[0] or {}).get("quote") or {}
    if not q:
        return None
    return _normalize_quote(q)


def _normalize_quote(q: dict) -> dict:
    """Lift the raw OpenAlgo quote dict into the shape v2 strategy
    expects (bid/ask/mid/spread_pct/quote_timestamp/quote_age_seconds).
    """
    bid = _safe_float(q.get("bid"))
    ask = _safe_float(q.get("ask"))
    mid = (bid + ask) / 2.0 if (bid and ask) else None
    spread_pct = (
        (ask - bid) / mid if (bid and ask and mid and mid > 0) else None
    )
    ts = q.get("timestamp") or q.get("ts")
    age_s = None
    if ts:
        try:
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            age_s = (pd.Timestamp.now(tz="UTC") - t).total_seconds()
        except Exception:
            pass
    return {
        "bid": bid, "ask": ask, "mid": mid,
        "spread_pct": spread_pct,
        "quote_timestamp": str(ts) if ts else None,
        "quote_age_seconds": age_s,
        "symbol_status": q.get("status"),
    }


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- orders


def submit_market_buy(
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    symbol: str,
    qty: int,
    time_in_force: str = "DAY",
) -> dict[str, Any]:
    """POST /api/v2/orders for a parent MARKET BUY. Returns the
    parsed body with ``_http_status`` annotated."""
    body = {
        "apikey": api_key,
        "instrument": {
            "venue_code": venue_code,
            "canonical_symbol": symbol,
        },
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "time_in_force": time_in_force,
        "session": "REGULAR",
    }
    r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


def submit_market_sell(
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    symbol: str,
    qty: int,
    time_in_force: str = "DAY",
) -> dict[str, Any]:
    """POST /api/v2/orders for a single SELL MARKET. Returns the parsed
    body with ``_http_status`` annotated. Caller validates http_status
    in (200, 201) before treating as accepted."""
    body = {
        "apikey": api_key,
        "instrument": {
            "venue_code": venue_code,
            "canonical_symbol": symbol,
        },
        "side": "SELL",
        "order_type": "MARKET",
        "quantity": str(qty),
        "quantity_unit": "WHOLE",
        "time_in_force": time_in_force,
        "session": "REGULAR",
    }
    r = http.post("/api/v2/orders", json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


def submit_oco_bracket(
    http: httpx.Client,
    api_key: str,
    *,
    venue_code: str,
    symbol: str,
    qty: int,
    target_price: float,
    stop_price: float,
    link_id: str,
    time_in_force: str = "GTC",
) -> dict[str, Any]:
    """POST /api/v2/orders/combo with an OCO (target LIMIT SELL + stop
    STOP SELL). Used to bracket an already-filled parent position. The
    GTC default protects against overnight gaps; pass ``DAY`` only when
    the bracket is meant to expire at session close.
    """
    body = {
        "apikey": api_key,
        "combo_type": "OCO",
        "time_in_force": time_in_force,
        "session": "REGULAR",
        "link_id": link_id,
        "legs": [
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": symbol,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "LIMIT",
                "price": str(round(float(target_price), 2)),
            },
            {
                "instrument_ref": {
                    "venue_code": venue_code,
                    "canonical_symbol": symbol,
                },
                "side": "SELL",
                "quantity": str(qty),
                "quantity_unit": "WHOLE",
                "order_type": "STOP",
                "trigger_price": str(round(float(stop_price), 2)),
            },
        ],
    }
    r = http.post("/api/v2/orders/combo",
                  json=body, headers=_api_headers(api_key))
    parsed = r.json() if r.content else {}
    parsed["_http_status"] = r.status_code
    return parsed


def cancel_order(
    http: httpx.Client, api_key: str, order_id: str,
) -> dict[str, Any]:
    """DELETE /api/v2/orders/<id>. Idempotent — treats 404 / already-
    terminal as success. Raises only on truly unexpected HTTP statuses.
    """
    if not order_id:
        return {"status": "noop", "reason": "no order_id"}
    r = http.request(
        "DELETE", f"/api/v2/orders/{order_id}",
        headers=_api_headers(api_key),
    )
    parsed = r.json() if r.content else {}
    if r.status_code == 200:
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    if r.status_code == 404:
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    err_msg = ""
    if isinstance(parsed, dict):
        err = parsed.get("error") or {}
        err_msg = (err.get("message") or "").lower()
    if any(k in err_msg for k in (
        "already inactive", "already_inactive",
        "already canceled", "already_canceled",
        "not found", "not_found",
    )):
        return {"status": "canceled", "order_id": order_id, "data": parsed}
    LOG.warning(
        "cancel_order(%s) unexpected response HTTP %d: %s",
        order_id, r.status_code, parsed,
    )
    return {
        "status": "error", "order_id": order_id,
        "http_status": r.status_code, "data": parsed,
    }


def fetch_positions(http: httpx.Client, api_key: str) -> list[dict]:
    r = http.get("/api/v2/positions", headers=_api_headers(api_key))
    r.raise_for_status()
    return r.json().get("data", {}).get("positions", []) or []


def fetch_open_orders(
    http: httpx.Client, api_key: str, status: str = "open",
) -> list[dict]:
    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"status": status})
    r.raise_for_status()
    return r.json().get("data", {}).get("orders", []) or []


def fetch_all_orders(http: httpx.Client, api_key: str) -> list[dict]:
    """GET /api/v2/orders?status=all — used by poll_fills."""
    r = http.get("/api/v2/orders",
                 headers=_api_headers(api_key),
                 params={"status": "all"})
    r.raise_for_status()
    return r.json().get("data", {}).get("orders", []) or []
