#!/usr/bin/env python3
"""Bowaka v2 — direct Alpaca Market Data multi-symbol bar fetch.

Bypasses the single-worker OpenAlgo server for the scanner's read-only
minute-bar prefetch. Alpaca's ``/v2/stocks/bars`` returns bars for many
symbols in ONE request (response keyed by symbol), so the whole universe
is fetched in a handful of paginated calls instead of N single-symbol
trips through the local server (which caps ~25-31 req/s, the bottleneck).

This mirrors ``broker/alpaca/api/bar_api.py`` exactly — same endpoint,
feed (``ALPACA_DATA_FEED``), params, ``limit``, ``next_page_token``
pagination, and ``t/o/h/l/c/v`` row parsing — so the output is identical
to the OpenAlgo ``/api/v2/bars`` path. The scanner flips
``scanner.bar_source`` between ``openalgo`` and ``alpaca_direct`` with no
behavior change beyond speed. Credential resolution mirrors
``broker/alpaca/api/auth_api.load_credentials`` precedence so the scanner
uses the SAME key the server uses.

Self-contained (no OpenAlgo-internal imports), matching the rest of the
bowaka v2 stack.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
import pandas as pd

LOG = logging.getLogger("bowaka_v2_alpaca_data")

_DATA_BASE_URL = "https://data.alpaca.markets"
_TIMEFRAME_MAP = {
    "1m": "1Min", "5m": "5Min", "15m": "15Min",
    "30m": "30Min", "1h": "1Hour", "1d": "1Day",
}
# Alpaca's max page limit is 10000 bars; 200 pages is far past any
# session's worth of 1m bars and short-circuits a runaway token loop.
_MAX_PAGES = 200
_PLACEHOLDER = frozenset({
    "", "YOUR_BROKER_API_KEY", "YOUR_BROKER_API_SECRET",
    "YOUR_BROKER_MARKET_API_KEY", "YOUR_BROKER_MARKET_API_SECRET",
    "YOUR_ALPACA_API_KEY", "YOUR_ALPACA_API_SECRET",
})


def _is_real(v: str | None) -> bool:
    return bool(v) and v not in _PLACEHOLDER


def _maybe_load_env_creds() -> None:
    """Populate os.environ from the repo ``.env`` so the scanner process
    (which the launcher only seeds with OPENALGO_API_KEY) can see the
    Alpaca creds + feed. No-op if creds are already in the environment;
    never overrides an existing var. Dependency-free manual parse."""
    if _is_real(os.environ.get("ALPACA_API_KEY")) or _is_real(
        os.environ.get("BROKER_API_KEY")
    ):
        return
    needed = {
        "ALPACA_API_KEY", "ALPACA_API_SECRET", "BROKER_API_KEY",
        "BROKER_API_SECRET", "BROKER_API_KEY_MARKET",
        "BROKER_API_SECRET_MARKET", "ALPACA_DATA_FEED", "ALPACA_PAPER",
        "ALPACA_LIVE_MODE",
    }
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in needed and not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")
    except Exception as e:  # pragma: no cover
        LOG.debug(".env manual load failed: %s", e)


def resolve_alpaca_data_auth() -> tuple[dict[str, str], str]:
    """Return ``(headers, feed)`` for the Alpaca data API.

    Mirrors ``broker/alpaca/api/auth_api.load_credentials`` precedence
    (explicit ALPACA_* wins; else BROKER_API_* with paper/live mode) so
    the scanner authenticates with the SAME key pair the OpenAlgo server
    uses — guaranteeing the direct path is parity-equivalent. Raises
    ``RuntimeError`` if no real credentials resolve.
    """
    _maybe_load_env_creds()
    live_mode = os.environ.get("ALPACA_LIVE_MODE")
    paper_env = os.environ.get("ALPACA_PAPER")
    if live_mode is not None:
        is_paper = live_mode.strip().lower() not in ("1", "true", "yes", "on")
    elif paper_env is not None:
        is_paper = paper_env.strip() != "0"
    else:
        is_paper = True

    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not (_is_real(key) and _is_real(secret)):
        if is_paper:
            key = os.environ.get("BROKER_API_KEY")
            secret = os.environ.get("BROKER_API_SECRET")
        else:
            key = os.environ.get("BROKER_API_KEY_MARKET")
            secret = os.environ.get("BROKER_API_SECRET_MARKET")
    if not (_is_real(key) and _is_real(secret)):
        raise RuntimeError(
            "Alpaca data credentials missing — set ALPACA_API_KEY/"
            "ALPACA_API_SECRET or BROKER_API_KEY/BROKER_API_SECRET "
            "(in .env or the environment)."
        )
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    feed = os.environ.get("ALPACA_DATA_FEED", "iex")
    return headers, feed


def make_data_client(
    headers: dict[str, str], *, timeout: float = 30.0, max_connections: int = 16,
) -> httpx.Client:
    return httpx.Client(
        base_url=_DATA_BASE_URL,
        headers=headers,
        timeout=httpx.Timeout(timeout, connect=5.0),
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        ),
    )


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """Map Alpaca bar rows (t/o/h/l/c/v) to the OpenAlgo-path frame
    shape: ``timestamp`` (UTC) + open/high/low/close/volume, ascending."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df.get("t"), utc=True, errors="coerce"),
        "open": pd.to_numeric(df.get("o"), errors="coerce"),
        "high": pd.to_numeric(df.get("h"), errors="coerce"),
        "low": pd.to_numeric(df.get("l"), errors="coerce"),
        "close": pd.to_numeric(df.get("c"), errors="coerce"),
        "volume": pd.to_numeric(df.get("v", 0), errors="coerce"),
    })
    return out.sort_values("timestamp").reset_index(drop=True)


def _fetch_chunk(
    client: httpx.Client, feed: str, syms: list[str], tf: str,
    start: datetime, end: datetime,
) -> dict[str, list[dict]]:
    """One symbol-chunk, walking all pages -> {symbol: [raw rows]}."""
    out: dict[str, list[dict]] = {s: [] for s in syms}
    params: dict[str, object] = {
        "symbols": ",".join(syms),
        "timeframe": tf,
        "start": _iso(start),
        "end": _iso(end),
        "limit": 10000,
        "feed": feed,
    }
    for _ in range(_MAX_PAGES):
        r = client.get("/v2/stocks/bars", params=params)
        r.raise_for_status()
        data = r.json()
        block = data.get("bars") or {}
        if isinstance(block, dict):
            for sym, page in block.items():
                out.setdefault(sym, []).extend(page or [])
        token = data.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    return out


def fetch_bars_multi(
    client: httpx.Client,
    feed: str,
    symbols: Iterable[str],
    interval: str,
    start: datetime,
    end: datetime,
    *,
    chunk_size: int = 200,
    concurrency: int = 4,
) -> dict[str, pd.DataFrame]:
    """Fetch bars for many symbols directly from Alpaca.

    Returns ``{symbol: DataFrame}`` for EVERY requested symbol (empty
    frame when Alpaca returned no bars), matching
    ``bowaka_v2_openalgo_client.fetch_bars_concurrent`` semantics so the
    two bar_source paths are drop-in interchangeable.
    """
    tf = _TIMEFRAME_MAP.get(interval)
    if tf is None:
        raise ValueError(f"unsupported interval {interval!r}")
    syms = list(dict.fromkeys(s for s in symbols if s))  # dedupe, ordered
    if not syms:
        return {}
    chunks = [syms[i:i + chunk_size] for i in range(0, len(syms), chunk_size)]
    merged: dict[str, list[dict]] = {}

    def _one(chunk: list[str]) -> dict[str, list[dict]]:
        return _fetch_chunk(client, feed, chunk, tf, start, end)

    workers = max(1, min(int(concurrency), len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_one, chunks):
            for sym, rows in res.items():
                merged.setdefault(sym, []).extend(rows)

    return {s: _rows_to_df(merged.get(s, [])) for s in syms}


__all__ = [
    "fetch_bars_multi",
    "make_data_client",
    "resolve_alpaca_data_auth",
]
