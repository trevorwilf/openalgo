"""Fake US :class:`BrokerQuoteAdapter` / :class:`BrokerBarAdapter`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from domain.broker_market_data import (
    AccountContext,
    NormalizedBar,
    NormalizedBarRequest,
    NormalizedQuote,
)
from services.broker_market_data_registry import (
    register_broker_bar_adapter,
    register_broker_quote_adapter,
)

BROKER_CODE = "fake_us"


class FakeUSQuoteAdapter:
    broker_code = BROKER_CODE

    def get_quote(
        self,
        instrument: Any,
        account_ctx: AccountContext,
    ) -> NormalizedQuote:
        return NormalizedQuote(
            instrument_id=instrument.instrument_id,
            venue_code=instrument.venue_code,
            canonical_symbol=instrument.canonical_symbol,
            bid=Decimal("100.01"),
            ask=Decimal("100.03"),
            last=Decimal("100.02"),
            bid_size=Decimal("100"),
            ask_size=Decimal("200"),
            timestamp=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
            currency=instrument.currency,
        )


class FakeUSBarAdapter:
    broker_code = BROKER_CODE

    def get_bars(
        self,
        instrument: Any,
        request: NormalizedBarRequest,
        account_ctx: AccountContext,
    ) -> list[NormalizedBar]:
        # Return three synthetic bars starting at request.start.
        out: list[NormalizedBar] = []
        step = timedelta(minutes=1)
        base = Decimal("100.00")
        for i in range(3):
            out.append(
                NormalizedBar(
                    ts=request.start + step * i,
                    open=base + Decimal(i) / 10,
                    high=base + Decimal(i) / 10 + Decimal("0.05"),
                    low=base + Decimal(i) / 10 - Decimal("0.05"),
                    close=base + Decimal(i) / 10 + Decimal("0.01"),
                    volume=Decimal("1000"),
                )
            )
        return out


def install_fake_us_market_data() -> tuple[FakeUSQuoteAdapter, FakeUSBarAdapter]:
    q = FakeUSQuoteAdapter()
    b = FakeUSBarAdapter()
    register_broker_quote_adapter(q)
    register_broker_bar_adapter(b)
    return q, b


__all__ = [
    "BROKER_CODE",
    "FakeUSBarAdapter",
    "FakeUSQuoteAdapter",
    "install_fake_us_market_data",
]
