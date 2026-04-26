"""Mock Schwab-LIKE quote adapter — deterministic fixture quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.account_context import AccountContext
from domain.broker_market_data import NormalizedQuote

BROKER_CODE = "_mock_schwab_like"

# Fixture quotes — keyed by (venue_code, canonical_symbol).
FIXTURE_QUOTES: dict[tuple[str, str], dict[str, Decimal]] = {
    ("XNAS", "AAPL"): {"bid": Decimal("150.10"), "ask": Decimal("150.12"), "last": Decimal("150.11")},
    ("XNAS", "MSFT"): {"bid": Decimal("400.55"), "ask": Decimal("400.60"), "last": Decimal("400.58")},
    ("XNAS", "SPY"): {"bid": Decimal("520.00"), "ask": Decimal("520.05"), "last": Decimal("520.02")},
}


class MockSchwabLikeQuoteAdapter:
    broker_code = BROKER_CODE

    def get_quote(self, instrument: Any, account_ctx: AccountContext) -> NormalizedQuote:
        key = (instrument.venue_code, instrument.canonical_symbol)
        defaults = FIXTURE_QUOTES.get(key, {
            "bid": Decimal("100.00"), "ask": Decimal("100.02"), "last": Decimal("100.01"),
        })
        return NormalizedQuote(
            instrument_id=instrument.instrument_id,
            venue_code=instrument.venue_code,
            canonical_symbol=instrument.canonical_symbol,
            bid=defaults["bid"],
            ask=defaults["ask"],
            last=defaults["last"],
            bid_size=Decimal("100"),
            ask_size=Decimal("100"),
            timestamp=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
            currency="USD",
        )


__all__ = ["BROKER_CODE", "MockSchwabLikeQuoteAdapter"]
