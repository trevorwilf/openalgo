"""Metrics façade — counters, gauges, reset helpers."""

from __future__ import annotations

import pytest

from utils import metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset_for_tests()
    yield
    metrics.reset_for_tests()


def test_counter_default_increment():
    metrics.counter("foo_total")
    assert metrics.get_counter_value("foo_total") == 1.0


def test_counter_with_labels():
    metrics.counter("bar_total", {"broker": "alpaca"})
    metrics.counter("bar_total", {"broker": "alpaca"})
    metrics.counter("bar_total", {"broker": "zerodha"})
    assert metrics.get_counter_value("bar_total", {"broker": "alpaca"}) == 2.0
    assert metrics.get_counter_value("bar_total", {"broker": "zerodha"}) == 1.0


def test_gauge_sets_value():
    metrics.gauge("lag", {"broker": "alpaca"}, value=12.5)
    assert metrics.get_gauge_value("lag", {"broker": "alpaca"}) == 12.5


def test_reset_clears_counters_and_gauges():
    metrics.counter("xx_total")
    metrics.gauge("yy", value=3.0)
    metrics.reset_for_tests()
    assert metrics.get_counter_value("xx_total") == 0.0
    assert metrics.get_gauge_value("yy") is None
