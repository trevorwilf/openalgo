"""Phase 1 — canonical interval vocabulary + broker translation."""

from __future__ import annotations

import pytest

from services.charts.intervals_service import (
    ALPACA_MAP,
    CANONICAL_INTERVALS,
    CanonicalInterval,
    ZERODHA_MAP,
    is_canonical,
    supported_for_broker,
    translate_for_broker,
)


def test_canonical_intervals_match_d08_vocabulary():
    expected = {
        "1s", "5s", "15s", "30s",
        "1m", "2m", "3m", "5m", "10m", "15m", "30m",
        "1h", "2h", "4h",
        "1d", "1w", "1mo",
    }
    assert set(CANONICAL_INTERVALS) == expected
    # Enum values cover the same set.
    assert {i.value for i in CanonicalInterval} == expected


def test_is_canonical_only_accepts_listed_intervals():
    for i in CANONICAL_INTERVALS:
        assert is_canonical(i)
    assert not is_canonical("1minute")
    assert not is_canonical("60s")


@pytest.mark.parametrize(
    "interval,native",
    [
        ("1m", "minute"),
        ("3m", "3minute"),
        ("15m", "15minute"),
        ("1h", "60minute"),
        ("1d", "day"),
    ],
)
def test_zerodha_translation(interval: str, native: str):
    assert translate_for_broker(interval, "zerodha") == native
    assert translate_for_broker(interval, "ZERODHA") == native


@pytest.mark.parametrize(
    "interval,native",
    [
        ("1m", "1Min"),
        ("5m", "5Min"),
        ("1h", "1Hour"),
        ("1d", "1Day"),
        ("1w", "1Week"),
        ("1mo", "1Month"),
    ],
)
def test_alpaca_translation(interval: str, native: str):
    assert translate_for_broker(interval, "alpaca") == native


def test_unsupported_interval_returns_none():
    assert translate_for_broker("2h", "zerodha") is None
    assert translate_for_broker("2m", "alpaca") is None


def test_unknown_broker_returns_none_or_empty():
    assert translate_for_broker("1m", "deribit") is None
    assert supported_for_broker("deribit") == []


def test_supported_for_broker_lists_only_translated_intervals():
    z = supported_for_broker("zerodha")
    assert set(z) == set(ZERODHA_MAP.keys())
    a = supported_for_broker("alpaca")
    assert set(a) == set(ALPACA_MAP.keys())
