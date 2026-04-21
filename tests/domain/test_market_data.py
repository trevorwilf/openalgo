"""Normalized market-data shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from domain.currency import Currency
from domain.instrument_ref import InstrumentRef
from domain.market_data import (
    NormalizedBar,
    NormalizedDepth,
    NormalizedDepthLevel,
    NormalizedQuote,
)


def _ref() -> InstrumentRef:
    return InstrumentRef(venue_code="NSE", canonical_symbol="SBIN")


def test_quote_roundtrip_utc() -> None:
    ts = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    q = NormalizedQuote(
        instrument=_ref(),
        timestamp=ts,
        bid=Decimal("100"),
        ask=Decimal("100.25"),
        last=Decimal("100.10"),
        currency=Currency.INR,
    )
    assert q.timestamp == ts


def test_quote_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        NormalizedQuote(
            instrument=_ref(),
            timestamp=datetime(2026, 4, 21, 12, 0, 0),
        )


def test_bar_rejects_naive_period_start() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        NormalizedBar(
            instrument=_ref(),
            period_start=datetime(2026, 4, 21, 12, 0, 0),
            period_end=datetime(2026, 4, 21, 13, 0, 0, tzinfo=timezone.utc),
            interval="1h",
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10000"),
        )


def test_bar_roundtrip() -> None:
    ps = datetime(2026, 4, 21, 9, 15, 0, tzinfo=timezone.utc)
    pe = datetime(2026, 4, 21, 9, 20, 0, tzinfo=timezone.utc)
    b = NormalizedBar(
        instrument=_ref(),
        period_start=ps,
        period_end=pe,
        interval="5m",
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("500"),
        currency=Currency.INR,
        venue_timezone="Asia/Kolkata",
    )
    assert b.interval == "5m"
    assert b.venue_timezone == "Asia/Kolkata"


def test_depth_roundtrip_and_tz_check() -> None:
    ts = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)
    d = NormalizedDepth(
        instrument=_ref(),
        timestamp=ts,
        bids=[
            NormalizedDepthLevel(price=Decimal("100"), size=Decimal("10")),
            NormalizedDepthLevel(price=Decimal("99.95"), size=Decimal("20")),
        ],
        asks=[
            NormalizedDepthLevel(price=Decimal("100.05"), size=Decimal("15")),
        ],
    )
    assert len(d.bids) == 2
    assert d.asks[0].price == Decimal("100.05")


def test_depth_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        NormalizedDepth(
            instrument=_ref(),
            timestamp=datetime(2026, 4, 21, 10, 0, 0),
        )
