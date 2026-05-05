"""Phase 4 — BarAggregator unit tests.

* Same-bucket trades: O fixed at first tick; H/L track extremes; C =
  last; V = sum.
* Bucket boundary: closed bar emitted with prior O/H/L/C/V; new
  forming bar opens with the boundary-crossing tick's price.
* Out-of-order tick (bucket < forming.bucket_t) is dropped silently.
* `feed_bar` accepts a server-emitted complete bar and emits on_close
  immediately.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.charts.bar_aggregator import (
    BarAggregator,
    bucket_size_seconds,
    bucket_start,
)


def test_bucket_start_for_known_intervals():
    # Floor of 1700000005 to a 1m bucket = 1700000005 // 60 * 60 = 1699999980.
    assert bucket_start("1m", 1700000005) == 1699999980
    # Floor to a 5m bucket: 1700000299 // 300 * 300 = 1700000100.
    assert bucket_start("5m", 1700000299) == 1700000100
    # Floor to a 1h bucket: 1700000005 // 3600 * 3600 = 1699999200.
    assert bucket_start("1h", 1700000005) == 1699999200


def test_bucket_size_seconds_table():
    assert bucket_size_seconds("1m") == 60
    assert bucket_size_seconds("5m") == 300
    assert bucket_size_seconds("1h") == 3600
    assert bucket_size_seconds("1mo") is None  # calendar-aware


def test_aggregator_single_bucket_aggregation():
    closes: list[dict] = []
    formings: list[dict] = []
    agg = BarAggregator(
        symbol="AAPL",
        timeframe="5m",
        on_forming=lambda b: formings.append(b.to_dict()),
        on_close=lambda b: closes.append(b.to_dict()),
    )
    base = 1700000100  # 5m-aligned
    agg.feed_trade(base + 1, Decimal("100.0"), Decimal("10"))
    agg.feed_trade(base + 60, Decimal("101.5"), Decimal("20"))  # H
    agg.feed_trade(base + 120, Decimal("99.5"), Decimal("5"))  # L
    agg.feed_trade(base + 180, Decimal("100.7"), Decimal("8"))  # C

    # Still inside the bucket — no close emitted yet.
    assert len(closes) == 0
    assert len(formings) == 4

    final = formings[-1]
    assert final["o"] == "100.0"
    assert final["h"] == "101.5"
    assert final["l"] == "99.5"
    assert final["c"] == "100.7"
    assert final["v"] == "43"


def test_aggregator_emits_close_at_bucket_boundary():
    closes: list[dict] = []
    agg = BarAggregator(
        symbol="AAPL",
        timeframe="1m",
        on_close=lambda b: closes.append(b.to_dict()),
    )
    base = 1700000040  # 1m-aligned
    agg.feed_trade(base + 1, Decimal("100.0"), Decimal("10"))
    agg.feed_trade(base + 30, Decimal("101.0"), Decimal("5"))
    # Cross into the next minute.
    agg.feed_trade(base + 60, Decimal("102.0"), Decimal("3"))
    assert len(closes) == 1
    closed = closes[0]
    assert closed["t"] == base
    assert closed["o"] == "100.0"
    assert closed["c"] == "101.0"
    assert closed["v"] == "15"


def test_aggregator_out_of_order_drops_late_tick():
    closes: list[dict] = []
    agg = BarAggregator(
        symbol="AAPL",
        timeframe="1m",
        on_close=lambda b: closes.append(b.to_dict()),
    )
    base = 1700000040
    agg.feed_trade(base + 30, Decimal("100.0"), Decimal("10"))
    # Late tick from the prior bucket — must not regress the forming bar
    # nor emit a duplicate close.
    agg.feed_trade(base - 30, Decimal("99.0"), Decimal("100"))
    assert agg.current is not None
    assert agg.current.o == Decimal("100.0")
    assert agg.current.v == Decimal("10")  # late volume not added
    assert len(closes) == 0


def test_aggregator_force_close_emits_pending_bar():
    closes: list[dict] = []
    agg = BarAggregator(
        symbol="AAPL",
        timeframe="1m",
        on_close=lambda b: closes.append(b.to_dict()),
    )
    agg.feed_trade(1700000040, Decimal("100.0"), Decimal("1"))
    agg.force_close()
    assert len(closes) == 1


def test_aggregator_feed_bar_treats_server_bar_as_authoritative():
    closes: list[dict] = []
    agg = BarAggregator(
        symbol="AAPL",
        timeframe="1m",
        on_close=lambda b: closes.append(b.to_dict()),
    )
    raw = {
        "t": 1700000040,
        "o": "100.0",
        "h": "101.5",
        "l": "99.5",
        "c": "100.7",
        "v": "43",
    }
    agg.feed_bar(raw)
    assert len(closes) == 1
    assert closes[0]["t"] == 1700000040
    assert closes[0]["v"] == "43"


def test_aggregator_rejects_non_canonical_timeframe():
    with pytest.raises(ValueError):
        BarAggregator(symbol="AAPL", timeframe="7m")
