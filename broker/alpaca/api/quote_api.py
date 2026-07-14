"""Alpaca quote adapter — BrokerQuoteAdapter implementation.

Uses Alpaca's market-data host (``data.alpaca.markets``) — the
trading host handles auth/account/orders, the data host handles
quotes/bars.

Trading-status source (investigated in priority order):

1. Streaming ``statuses`` channel — Alpaca's market-data websocket
   does carry real-time trading-status (halt/resume/LULD) messages,
   but the streaming adapter runs under the WebSocket proxy process,
   not the Flask request path, and no cross-process status map
   exists today. Deferred until a shared status bus is available.
2. Snapshot trade/quote condition codes — the raw SIP condition
   letters are passed through but an *ongoing* halt is not reliably
   inferable from the last trade's conditions; mapping them would
   produce false negatives. Not used.
3. Assets endpoint (implemented floor): the trading host's
   ``/v2/assets/{symbol}`` reports ``status`` (active/inactive) and
   ``tradable``. Coarse and non-realtime, but it is authoritative
   for "can an order be placed right now" — a halted or restricted
   symbol reports ``tradable: false``. Cached with a short TTL so
   the extra call does not double per-quote latency.

The result rides in ``NormalizedQuote.metadata["status"]``
("active" / "halted" / "inactive", or None when the lookup fails) —
additive: no change to the pinned top-level quote shape.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from domain.broker_market_data import (
    AccountContext,
    BrokerQuoteAdapter,
    NormalizedQuote,
)
from domain.currency import Currency
from domain.errors import UnsupportedCapability
from utils.logging import get_logger

logger = get_logger(__name__)

# Per-symbol trading-status cache: {symbol: (fetched_monotonic, status)}.
# Module-level so per-request adapter instances share it.
_ASSET_STATUS_TTL_SECONDS = 60.0
_ASSET_STATUS_CACHE: dict[str, tuple[float, str | None]] = {}


class AlpacaQuoteAdapter:
    broker_code = "alpaca"

    def __init__(
        self, auth: AlpacaAuth | None = None, client: httpx.Client | None = None
    ) -> None:
        self._auth = auth
        self._client = client

    def _resolve_auth(self) -> AlpacaAuth:
        if self._auth is None:
            return authenticate()
        return self._auth

    def _get(self, url_path: str, params: dict | None = None) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.get(url_path, params=params)
        else:
            with httpx.Client(
                base_url=auth.data_base_url,
                headers=dict(auth.headers),
                timeout=httpx.Timeout(10.0, connect=5.0),
            ) as c:
                r = c.get(url_path, params=params)
        r.raise_for_status()
        return r.json()

    def _get_trading_host(self, url_path: str) -> dict:
        """GET against the TRADING host (assets/account/orders live
        there, not on the data host). An injected test client is used
        as-is — its transport dispatches on path."""
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.get(url_path)
        else:
            with httpx.Client(
                base_url=auth.base_url,
                headers=dict(auth.headers),
                timeout=httpx.Timeout(10.0, connect=5.0),
            ) as c:
                r = c.get(url_path)
        r.raise_for_status()
        return r.json()

    def _trading_status(self, symbol: str) -> str | None:
        """Coarse per-symbol trading status from the assets endpoint
        (source #3 in the module docstring), TTL-cached. Returns
        "active" / "halted" / "inactive", or None when the lookup
        fails — callers treat None as status-unknown, never as
        tradable-confirmation."""
        now = time.monotonic()
        cached = _ASSET_STATUS_CACHE.get(symbol)
        if cached is not None and now - cached[0] < _ASSET_STATUS_TTL_SECONDS:
            return cached[1]
        try:
            asset = self._get_trading_host(f"/v2/assets/{symbol}")
        except Exception as e:
            logger.debug("alpaca asset-status lookup failed for %s: %s", symbol, e)
            _ASSET_STATUS_CACHE[symbol] = (now, None)
            return None
        if not isinstance(asset, dict):
            _ASSET_STATUS_CACHE[symbol] = (now, None)
            return None
        raw_status = str(asset.get("status") or "").lower()
        tradable = asset.get("tradable")
        if raw_status and raw_status != "active":
            status = "inactive"
        elif tradable is False:
            # Active listing that Alpaca will not accept orders for
            # right now — halted or restricted. Fail-safe mapping: the
            # strategy halt gate blocks it.
            status = "halted"
        else:
            status = "active"
        _ASSET_STATUS_CACHE[symbol] = (now, status)
        return status

    def get_quote(
        self,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> NormalizedQuote:
        if instrument.venue_code not in {"XNAS", "XNYS", "ARCX", "BATS"}:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="venue",
                details=f"Alpaca does not trade venue {instrument.venue_code!r}",
            )
        symbol = instrument.broker_native_symbol or instrument.canonical_symbol
        # Use the snapshot endpoint — one call returns latestTrade
        # (real last-trade price), latestQuote (NBBO bid/ask),
        # dailyBar (intraday OHLCV), and prevDailyBar (prev close).
        # The previous /quotes/latest endpoint omitted last-trade so
        # ``last`` had to fall back to the ask price, which the v1
        # bridge then propagated as ltp/high/low/open/prev_close.
        # Pin the data feed (see bar_api.py for the full rationale —
        # snapshot is on data.alpaca.markets too, so the same SIP-default
        # 403 trap applies). ALPACA_DATA_FEED defaults to "iex".
        data = self._get(
            f"/v2/stocks/{symbol}/snapshot",
            params={"feed": os.environ.get("ALPACA_DATA_FEED", "iex")},
        )
        latest_quote = data.get("latestQuote") or {}
        latest_trade = data.get("latestTrade") or {}
        daily_bar = data.get("dailyBar") or {}
        prev_daily_bar = data.get("prevDailyBar") or {}
        # Prefer the trade timestamp; fall back to quote timestamp.
        ts_raw = latest_trade.get("t") or latest_quote.get("t")
        ts = _parse_ts(ts_raw) if ts_raw else None

        # Prefer the actual last-trade price; if the snapshot has no
        # trade today (rare on a heavily-traded symbol but possible
        # for thinly-traded ones outside RTH), fall back to the
        # bid+ask midpoint, which is a more honest "last" than
        # picking either side.
        last = _opt_decimal(latest_trade.get("p"))
        if last is None:
            bid_d = _opt_decimal(latest_quote.get("bp"))
            ask_d = _opt_decimal(latest_quote.get("ap"))
            if bid_d is not None and ask_d is not None and bid_d > 0 and ask_d > 0:
                last = (bid_d + ask_d) / 2

        return NormalizedQuote(
            instrument_id=instrument.instrument_id,
            venue_code=instrument.venue_code,
            canonical_symbol=instrument.canonical_symbol,
            bid=_opt_decimal(latest_quote.get("bp")),
            ask=_opt_decimal(latest_quote.get("ap")),
            last=last,
            bid_size=_opt_decimal(latest_quote.get("bs")),
            ask_size=_opt_decimal(latest_quote.get("as")),
            timestamp=ts,
            currency=Currency.USD,
            metadata={
                "raw_exchange": latest_quote.get("x"),
                # Coarse trading status from the assets endpoint (see
                # module docstring) — additive metadata field consumed
                # by the strategy-side halt gate.
                "status": self._trading_status(symbol),
                # OHLCV — populated for the v1 bridge so /quotes,
                # /multiquotes, /depth render correct daily bars
                # instead of stamping the same `last` value into
                # high/low/open/prev_close.
                "open": _opt_decimal(daily_bar.get("o")),
                "high": _opt_decimal(daily_bar.get("h")),
                "low": _opt_decimal(daily_bar.get("l")),
                "close": _opt_decimal(daily_bar.get("c")),
                "volume": _opt_decimal(daily_bar.get("v")),
                "prev_close": _opt_decimal(prev_daily_bar.get("c")),
                "trade_size": _opt_decimal(latest_trade.get("s")),
            },
        )


def _opt_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None


def _parse_ts(raw: str) -> datetime:
    s = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


__all__ = ["AlpacaQuoteAdapter"]
