"""Phase 8 — Zerodha NIFTY multi-market fixture.

Verifies the chart datafeed contract works end-to-end for an India
broker. NIFTY is a calculated index — the bars are synthetic and the
contract gate is that the India parity arbiter remains 41/41 with
the chart workspace running.
"""

from __future__ import annotations

from decimal import Decimal

from services.charts.bar_aggregator import BarAggregator


def nifty_fixture(n: int = 100) -> list[dict]:
    """Synthetic NIFTY 1m bars covering ~100 minutes of NSE
    regular-hours trading.

    NSE 09:15 IST = 03:45 UTC. We use UTC seconds at the wire layer
    per HANDOFF P-06; the chart workspace renders in IST via the
    venue session service, never via a hardcoded offset.
    """
    # 2024-01-02 09:15 IST = 03:45 UTC.
    base = 1704166500  # 2024-01-02T03:45:00Z
    bars = []
    price = 21500.0
    for i in range(n):
        d = (1.5 if i % 3 else -0.8)
        new = price + d
        bars.append(
            {
                "t": base + i * 60,
                "o": str(price),
                "h": str(max(price, new) + 0.5),
                "l": str(min(price, new) - 0.5),
                "c": str(new),
                "v": str(0),  # NIFTY index has no volume.
                "oi": None,
            }
        )
        price = new
    return bars


def test_nifty_fixture_uses_utc_wire_timestamps():
    bars = nifty_fixture(60)
    # 09:15 IST = 03:45 UTC, in epoch seconds.
    assert bars[0]["t"] == 1704166500


def test_aggregator_consumes_nifty_fixture():
    closes: list = []
    agg = BarAggregator(symbol="NIFTY", timeframe="5m", on_close=lambda b: closes.append(b))
    for b in nifty_fixture(60):
        agg.feed_trade(int(b["t"]), Decimal(b["c"]), Decimal("0"))
    assert 10 <= len(closes) <= 12


def test_chart_code_does_not_hardcode_ist_offset():
    """Spot-check that the chart datafeed source files don't carry
    the legacy 5.5*60*60*1000 IST offset literal. The full literal
    scan lives at frontend/scripts/literal_scan.mjs but Phase 8 also
    wants a python-side spot check for the backend services."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    services_charts = repo_root / "services" / "charts"
    forbidden = ("5.5*60*60*1000", "5.5 * 60 * 60 * 1000", "Asia/Kolkata", "'IST'")
    for py in services_charts.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py}: forbidden token {token!r}"
