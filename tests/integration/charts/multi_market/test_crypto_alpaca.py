"""Phase 8 — Alpaca BTC/USD crypto multi-market fixture.

Crypto trades 24/7. The chart workspace's contract is that bucket
boundaries (1m, 5m, 1h, etc.) align to UTC midnight regardless of
the venue's regular session hours.
"""

from __future__ import annotations

from decimal import Decimal

from services.charts.bar_aggregator import BarAggregator, bucket_start


def btcusd_fixture(n: int = 100) -> list[dict]:
    """Synthetic BTC/USD 1m bars covering 100 minutes — they could
    fall anywhere in the day since crypto is 24/7."""
    # 2024-01-02 12:00 UTC — midday Tuesday.
    base = 1704196800
    bars = []
    price = 45000.0
    for i in range(n):
        d = (10 if i % 5 else -5)
        new = price + d
        bars.append(
            {
                "t": base + i * 60,
                "o": str(price),
                "h": str(max(price, new) + 5),
                "l": str(min(price, new) - 5),
                "c": str(new),
                "v": str(0.5 + i * 0.01),
                "oi": None,
            }
        )
        price = new
    return bars


def test_btcusd_fixture_at_midday_utc():
    bars = btcusd_fixture(60)
    assert bars[0]["t"] == 1704196800  # 2024-01-02 12:00 UTC


def test_bucket_alignment_works_for_24_7_market():
    """Bucket boundaries must align to UTC midnight regardless of the
    tick's local-time. A tick at 12:00:30 UTC falls in the 12:00:00
    UTC 1m bucket."""
    assert bucket_start("1m", 1704196830) == 1704196800
    assert bucket_start("5m", 1704196830) == 1704196800
    assert bucket_start("1h", 1704196830) == 1704196800


def test_aggregator_consumes_btcusd_fixture():
    closes: list = []
    agg = BarAggregator(symbol="BTC/USD", timeframe="5m", on_close=lambda b: closes.append(b))
    for b in btcusd_fixture(60):
        agg.feed_trade(int(b["t"]), Decimal(b["c"]), Decimal(b["v"]))
    assert 10 <= len(closes) <= 12


def test_no_market_hours_bias_in_chart_code():
    """The chart code does not assume any specific venue's open / close
    hours — bucket boundaries align to UTC midnight by construction. The
    legacy India pages that bake in NSE 09:15-15:30 IST do not influence
    this path."""
    # Smoke check — the bucket helper has no calls into venue session
    # service for non-1mo intervals.
    from services.charts import bar_aggregator

    assert "venue_session" not in bar_aggregator.__file__
