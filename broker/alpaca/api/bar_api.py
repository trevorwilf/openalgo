"""Alpaca bar adapter — BrokerBarAdapter implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from broker.alpaca.api.auth_api import AlpacaAuth, authenticate
from domain.broker_market_data import (
    AccountContext,
    BrokerBarAdapter,
    NormalizedBar,
    NormalizedBarRequest,
)
from domain.errors import UnsupportedCapability


_TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "1d": "1Day",
}


class AlpacaBarAdapter:
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
                timeout=httpx.Timeout(15.0, connect=5.0),
            ) as c:
                r = c.get(url_path, params=params)
        r.raise_for_status()
        return r.json()

    def get_bars(
        self,
        instrument: Any,
        request: NormalizedBarRequest,
        account_ctx: AccountContext,
    ) -> list[NormalizedBar]:
        if instrument.venue_code not in {"XNAS", "XNYS", "ARCX", "BATS"}:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="venue",
                details=f"Alpaca does not trade venue {instrument.venue_code!r}",
            )
        tf = _TIMEFRAME_MAP.get(request.interval)
        if tf is None:
            raise UnsupportedCapability(
                broker_code=self.broker_code,
                capability_name="bar_interval",
                details=(
                    f"Alpaca adapter maps only {list(_TIMEFRAME_MAP)}; got "
                    f"{request.interval!r}"
                ),
            )
        symbol = instrument.broker_native_symbol or instrument.canonical_symbol
        params = {
            "symbols": symbol,
            "timeframe": tf,
            "start": _iso(request.start),
            "end": _iso(request.end),
            "limit": 10000,
        }
        data = self._get("/v2/stocks/bars", params=params)
        bars_block = data.get("bars", {})
        rows = bars_block.get(symbol, []) if isinstance(bars_block, dict) else []
        return [_row_to_bar(r) for r in rows]


def _row_to_bar(row: dict) -> NormalizedBar:
    return NormalizedBar(
        ts=_parse_ts(row["t"]),
        open=Decimal(str(row["o"])),
        high=Decimal(str(row["h"])),
        low=Decimal(str(row["l"])),
        close=Decimal(str(row["c"])),
        volume=Decimal(str(row.get("v", "0"))),
    )


def _parse_ts(raw: str) -> datetime:
    s = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["AlpacaBarAdapter"]
