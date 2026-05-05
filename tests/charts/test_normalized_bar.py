"""Phase 1 — ChartNormalizedBar Decimal/UTC-seconds round-trip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from services.charts.normalized_bar import ChartNormalizedBar, from_broker_bar


def test_to_dict_serializes_decimals_as_strings():
    b = ChartNormalizedBar(
        t=1_700_000_000,
        o=Decimal("100.25"),
        h=Decimal("101.5"),
        l=Decimal("99.75"),
        c=Decimal("100.875"),
        v=Decimal("12345"),
        oi=None,
    )
    d = b.to_dict()
    assert d["t"] == 1_700_000_000
    assert d["o"] == "100.25"
    assert d["h"] == "101.5"
    assert d["l"] == "99.75"
    assert d["c"] == "100.875"
    assert d["v"] == "12345"
    assert d["oi"] is None


def test_from_dict_round_trip_preserves_decimal_precision():
    src = {
        "t": 1700000000,
        "o": "100.250000001",
        "h": "101.500000002",
        "l": "99.750000003",
        "c": "100.875000004",
        "v": "12345",
        "oi": "999.5",
    }
    b = ChartNormalizedBar.from_dict(src)
    # No float coercion — exact decimal preservation.
    assert b.o == Decimal("100.250000001")
    assert b.oi == Decimal("999.5")
    assert b.to_dict() == src


def test_from_broker_bar_with_datetime_ts():
    @dataclass
    class _BrokerBar:
        ts: datetime
        open: Decimal
        high: Decimal
        low: Decimal
        close: Decimal
        volume: Decimal | None
        open_interest: Decimal | None = None

    src = _BrokerBar(
        ts=datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc),
        open=Decimal("10.0"),
        high=Decimal("11.0"),
        low=Decimal("9.5"),
        close=Decimal("10.5"),
        volume=Decimal("100"),
    )
    b = from_broker_bar(src)
    assert b.t == 1704101400  # 2024-01-01T09:30:00Z
    assert b.o == Decimal("10.0")
    assert b.oi is None


def test_from_broker_bar_with_int_ts_and_oi():
    @dataclass
    class _BrokerBar:
        ts: int
        open: Decimal
        high: Decimal
        low: Decimal
        close: Decimal
        volume: Decimal | None
        open_interest: Decimal | None

    src = _BrokerBar(1700000000, Decimal("1"), Decimal("2"), Decimal("0"),
                     Decimal("1.5"), Decimal("10"), Decimal("42"))
    b = from_broker_bar(src)
    assert b.t == 1700000000
    assert b.oi == Decimal("42")
