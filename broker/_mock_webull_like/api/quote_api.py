"""Mock Webull-LIKE quote adapter — deterministic fixture quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.account_context import AccountContext
from domain.broker_market_data import NormalizedQuote

BROKER_CODE = "_mock_webull_like"

FIXTURE_QUOTES: dict[tuple[str, str], dict[str, Decimal]] = {
    ("XNAS", "AAPL"): {"bid": Decimal("150.05"), "ask": Decimal("150.07"), "last": Decimal("150.06")},
    ("XNAS", "MSFT"): {"bid": Decimal("400.40"), "ask": Decimal("400.45"), "last": Decimal("400.42")},
}


class MockWebullLikeQuoteAdapter:
    broker_code = BROKER_CODE

    def get_quote(self, instrument: Any, account_ctx: AccountContext) -> NormalizedQuote:
        key = (instrument.venue_code, instrument.canonical_symbol)
        defaults = FIXTURE_QUOTES.get(key, {
            "bid": Decimal("99.00"), "ask": Decimal("99.02"), "last": Decimal("99.01"),
        })
        return NormalizedQuote(
            instrument_id=instrument.instrument_id,
            venue_code=instrument.venue_code,
            canonical_symbol=instrument.canonical_symbol,
            bid=defaults["bid"],
            ask=defaults["ask"],
            last=defaults["last"],
            bid_size=Decimal("50"),
            ask_size=Decimal("50"),
            timestamp=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
            currency="USD",
        )


__all__ = ["BROKER_CODE", "MockWebullLikeQuoteAdapter"]
