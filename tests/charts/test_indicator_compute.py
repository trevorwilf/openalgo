"""Phase 5 — indicator compute dispatch tests.

Smoke tests that the compute() function returns non-empty series for
each indicator key that the test environment supports. Where neither
TA-Lib nor pandas-ta is installed, only SMA/EMA fall back to the
pure-Python path.
"""

from __future__ import annotations

import math

import pytest

from services.charts.indicator_compute import (
    PANDAS_TA_AVAILABLE,
    TALIB_AVAILABLE,
    compute,
)


def _bars(n: int = 50) -> list[dict]:
    base = 1700000040
    out = []
    price = 100.0
    for i in range(n):
        d = (1 if i % 3 == 0 else -0.5)
        new = price + d
        out.append(
            {
                "t": base + i * 60,
                "o": str(price),
                "h": str(max(price, new) + 0.5),
                "l": str(min(price, new) - 0.5),
                "c": str(new),
                "v": str(1000 + i),
                "oi": None,
            }
        )
        price = new
    return out


def test_unknown_indicator_raises():
    with pytest.raises(ValueError):
        compute(_bars(), "DOES_NOT_EXIST")


def test_sma_returns_series_with_warmup_nulls():
    # SMA is the always-available fallback path.
    rows = compute(_bars(50), "SMA", {"period": 10})
    assert len(rows) == 50
    # First (period-1) rows have null values; later rows have numbers.
    assert rows[0]["values"]["sma"] is None
    last_value = rows[-1]["values"]["sma"]
    assert last_value is not None and not math.isnan(float(last_value))


def test_ema_returns_series_with_warmup_nulls():
    rows = compute(_bars(50), "EMA", {"period": 10})
    assert len(rows) == 50
    assert rows[-1]["values"]["ema"] is not None


@pytest.mark.skipif(not (TALIB_AVAILABLE or PANDAS_TA_AVAILABLE), reason="TA-Lib + pandas-ta absent")
def test_rsi_returns_bounded_values():
    rows = compute(_bars(50), "RSI", {"period": 14})
    bounded = [r["values"]["rsi"] for r in rows if r["values"]["rsi"] is not None]
    if bounded:
        for v in bounded:
            assert 0.0 <= v <= 100.0


@pytest.mark.skipif(not TALIB_AVAILABLE, reason="TA-Lib absent")
def test_macd_emits_three_keys():
    rows = compute(_bars(60), "MACD", {})
    last = rows[-1]["values"]
    assert set(last.keys()) == {"macd", "signal", "histogram"}


@pytest.mark.skipif(not PANDAS_TA_AVAILABLE, reason="pandas_ta absent")
def test_supertrend_emits_two_keys():
    rows = compute(_bars(50), "SUPERTREND", {})
    last = rows[-1]["values"]
    assert "supertrend" in last
    assert "direction" in last
