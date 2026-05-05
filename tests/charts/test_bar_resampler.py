"""Phase 1 — bar resampler perf + correctness.

Acceptance (HANDOFF C1-T7): 1y of 1m AAPL → 1d in <500ms. We use a
synthetic deterministic dataset of equivalent size (~390 bars/day *
252 trading days ≈ 98_280 1m bars) since real fixtures aren't required
for the perf gate.
"""

from __future__ import annotations

import time

import pytest

from services.charts.bar_resampler import POLARS_AVAILABLE, resample_bars

pytestmark = pytest.mark.skipif(
    not POLARS_AVAILABLE, reason="polars not installed"
)


def _synthetic_1m_bars(num: int, start_ts: int = 1_700_000_000) -> list[dict]:
    """Generate `num` 1-minute bars starting at start_ts (UTC seconds)."""
    bars = []
    price = 100.0
    for i in range(num):
        # Deterministic pseudo-volatility (zigzag).
        delta = 0.5 if (i % 7) < 4 else -0.4
        new_price = max(1.0, price + delta)
        bars.append(
            {
                "t": start_ts + i * 60,
                "o": str(price),
                "h": str(max(price, new_price) + 0.1),
                "l": str(min(price, new_price) - 0.1),
                "c": str(new_price),
                "v": str(1000 + (i % 50)),
                "oi": None,
            }
        )
        price = new_price
    return bars


def test_resample_1m_to_1m_is_identity_modulo_dedup():
    bars = _synthetic_1m_bars(10)
    out = resample_bars(bars, "1m")
    assert len(out) == 10
    # Sorted by t.
    assert all(out[i]["t"] < out[i + 1]["t"] for i in range(len(out) - 1))


def test_resample_aggregates_ohlcv_correctly():
    """Hand-computed expectation for 5 1m bars rolled into 5m buckets.

    Polars's `group_by_dynamic` uses calendar-aligned buckets (00:00,
    00:05, 00:10, …). Picking a 5m-aligned start makes the expectation
    clean: all 5 bars fall in one bucket [00:00, 00:05).

    1700000100 = 2023-11-14 20:55:00 UTC, which is 5m-aligned.
    """
    base = 1700000100
    bars = [
        {"t": base + 0,   "o": "100", "h": "101", "l": "99",   "c": "100.5", "v": "10", "oi": None},
        {"t": base + 60,  "o": "100.5", "h": "102", "l": "100", "c": "101",   "v": "20", "oi": None},
        {"t": base + 120, "o": "101",   "h": "103", "l": "100.5","c": "102",   "v": "30", "oi": None},
        {"t": base + 180, "o": "102",   "h": "104", "l": "101", "c": "103",   "v": "40", "oi": None},
        {"t": base + 240, "o": "103",   "h": "104.5","l": "102", "c": "104",   "v": "50", "oi": None},
    ]
    out = resample_bars(bars, "5m")
    assert len(out) == 1, f"expected 1 bucket, got {len(out)}: {out}"
    bar = out[0]
    # Open from first bar of bucket; close from last.
    assert float(bar["o"]) == pytest.approx(100.0)
    assert float(bar["c"]) == pytest.approx(104.0)
    # High = max of all highs in bucket.
    assert float(bar["h"]) == pytest.approx(104.5)
    # Low = min of all lows.
    assert float(bar["l"]) == pytest.approx(99.0)
    # Volume = sum.
    assert float(bar["v"]) == pytest.approx(10 + 20 + 30 + 40 + 50)


def test_resample_unknown_interval_raises():
    with pytest.raises(ValueError):
        resample_bars(_synthetic_1m_bars(5), "7m")


def test_resample_empty_returns_empty():
    assert resample_bars([], "5m") == []


def test_perf_1y_of_1m_to_1d_under_500ms():
    """C1-T7 perf gate. 98,280 continuous-time 1m bars → 1d in <500ms.

    The synthetic generator emits 24/7 bars, so 98,280 minutes ≈ 68 days
    of buckets — that's the data shape we're benchmarking the resampler
    against, not market-hours equivalence.
    """
    bars = _synthetic_1m_bars(98_280)
    t0 = time.perf_counter()
    out = resample_bars(bars, "1d")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # 98,280 / 1440 ≈ 68 days; allow fence-post slack.
    assert 60 <= len(out) <= 80, f"unexpected day count: {len(out)}"
    assert elapsed_ms < 500, f"1y/1m → 1d took {elapsed_ms:.1f}ms (target <500ms)"
