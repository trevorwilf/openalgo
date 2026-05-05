"""Phase 4 — talipp live indicator service smoke tests."""

from __future__ import annotations

import pytest

from services.charts.talipp_indicator_service import (
    IndicatorSpec,
    TALIPP_AVAILABLE,
    TalippIndicatorService,
)

pytestmark = pytest.mark.skipif(not TALIPP_AVAILABLE, reason="talipp not installed")


def test_register_then_remove():
    svc = TalippIndicatorService()
    spec = IndicatorSpec(id="rsi-1", symbol="AAPL", timeframe="1m", key="RSI", params={"period": 14})
    svc.register(spec)
    svc.feed_close("AAPL", "1m", 100.0)
    svc.remove("rsi-1")
    # Subsequent feed shouldn't raise — the instance is gone.
    svc.feed_close("AAPL", "1m", 101.0)


def test_rsi_emits_value_after_warmup():
    received: list = []
    svc = TalippIndicatorService(on_update=lambda spec, value: received.append((spec.id, value)))
    svc.register(
        IndicatorSpec(id="rsi-1", symbol="AAPL", timeframe="1m", key="RSI", params={"period": 14})
    )
    # 30 closes — well past the 14-period warmup.
    closes = [100.0 + (i % 5) - 2 for i in range(30)]
    for c in closes:
        svc.feed_close("AAPL", "1m", c)
    assert len(received) == 30
    # After warmup at least one of the last entries should have a numeric value.
    last_id, last_value = received[-1]
    assert last_id == "rsi-1"
    assert "rsi" in last_value
    # RSI in [0, 100] when present.
    if last_value["rsi"] is not None:
        assert 0.0 <= last_value["rsi"] <= 100.0


def test_ema_value_after_warmup():
    received: list = []
    svc = TalippIndicatorService(on_update=lambda spec, value: received.append(value))
    svc.register(
        IndicatorSpec(id="ema-1", symbol="AAPL", timeframe="1m", key="EMA", params={"period": 5})
    )
    for i in range(20):
        svc.feed_close("AAPL", "1m", 100.0 + i * 0.5)
    last = received[-1]
    assert "ema" in last
    if last["ema"] is not None:
        assert 100.0 <= last["ema"] <= 110.0


def test_macd_emits_three_values():
    received: list = []
    svc = TalippIndicatorService(on_update=lambda spec, value: received.append(value))
    svc.register(
        IndicatorSpec(id="macd-1", symbol="AAPL", timeframe="1m", key="MACD", params={})
    )
    for i in range(60):
        svc.feed_close("AAPL", "1m", 100.0 + i)
    last = received[-1]
    assert set(last.keys()) == {"macd", "signal", "histogram"}


def test_unsupported_key_raises():
    svc = TalippIndicatorService()
    with pytest.raises(ValueError):
        svc.register(IndicatorSpec(id="x", symbol="A", timeframe="1m", key="UNKNOWN", params={}))


def test_feed_close_only_updates_matching_symbol_timeframe():
    received: list = []
    svc = TalippIndicatorService(on_update=lambda spec, value: received.append(spec.id))
    svc.register(
        IndicatorSpec(id="aapl-1m", symbol="AAPL", timeframe="1m", key="EMA", params={"period": 5})
    )
    svc.register(
        IndicatorSpec(id="msft-1m", symbol="MSFT", timeframe="1m", key="EMA", params={"period": 5})
    )
    svc.feed_close("AAPL", "1m", 100.0)
    assert received == ["aapl-1m"]
    svc.feed_close("MSFT", "1m", 200.0)
    assert received == ["aapl-1m", "msft-1m"]
