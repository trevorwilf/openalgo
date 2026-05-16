"""Alpaca quote adapter — BrokerQuoteAdapter implementation.

Uses Alpaca's market-data host (``data.alpaca.markets``) — the
trading host handles auth/account/orders, the data host handles
quotes/bars.
"""

from __future__ import annotations

import os
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
