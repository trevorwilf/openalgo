"""Alpaca quote adapter — BrokerQuoteAdapter implementation.

Uses Alpaca's market-data host (``data.alpaca.markets``) — the
trading host handles auth/account/orders, the data host handles
quotes/bars.
"""

from __future__ import annotations

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

    def _get(self, url_path: str) -> dict:
        auth = self._resolve_auth()
        if self._client is not None:
            r = self._client.get(url_path)
        else:
            with httpx.Client(
                base_url=auth.data_base_url,
                headers=dict(auth.headers),
                timeout=httpx.Timeout(10.0, connect=5.0),
            ) as c:
                r = c.get(url_path)
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
        data = self._get(f"/v2/stocks/{symbol}/quotes/latest")
        quote = data.get("quote", {})
        ts_raw = quote.get("t")
        ts = None
        if ts_raw:
            ts = _parse_ts(ts_raw)
        return NormalizedQuote(
            instrument_id=instrument.instrument_id,
            venue_code=instrument.venue_code,
            canonical_symbol=instrument.canonical_symbol,
            bid=_opt_decimal(quote.get("bp")),
            ask=_opt_decimal(quote.get("ap")),
            last=_opt_decimal(quote.get("ap") or quote.get("bp")),
            bid_size=_opt_decimal(quote.get("bs")),
            ask_size=_opt_decimal(quote.get("as")),
            timestamp=ts,
            currency=Currency.USD,
            metadata={"raw_exchange": quote.get("x")},
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
