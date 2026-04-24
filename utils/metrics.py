"""Tiny metrics façade with a no-op fallback.

Backed by ``prometheus_client`` if installed; otherwise operations are
debug-logs so callers can be unconditional.

Usage::

    from utils.metrics import counter, gauge

    counter("promoted_legacy_fallback_total", {"broker": "alpaca"})
    gauge("instrument_sync_lag_seconds", {"broker": "alpaca"}, 12.3)

Metric names are snake_case, label values are strings. Prefer a small
fixed label cardinality — broker code, venue code, error code, etc.

Tests can inspect registered counters/gauges via
:func:`get_counter_value` / :func:`get_gauge_value` and reset state
via :func:`reset_for_tests`.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Mapping

from utils.logging import get_logger

logger = get_logger(__name__)

try:  # Prefer prometheus_client if available.
    from prometheus_client import Counter, Gauge  # type: ignore
    _HAS_PROM = True
except Exception:  # pragma: no cover - exercise of fallback only
    Counter = None  # type: ignore
    Gauge = None  # type: ignore
    _HAS_PROM = False


_lock = threading.Lock()
_counters: dict[str, Any] = {}
_gauges: dict[str, Any] = {}

# In-process mirror of counter/gauge values so tests can read them
# without importing prometheus internals.
_counter_values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_gauge_values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def _canonical_labels(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def counter(
    name: str,
    labels: Mapping[str, str] | None = None,
    value: float = 1.0,
) -> None:
    """Increment a counter by ``value``. Default 1."""
    canon = _canonical_labels(labels)
    key = (name, canon)
    with _lock:
        _counter_values[key] = _counter_values.get(key, 0.0) + value
    if not _HAS_PROM:
        logger.debug("metrics.counter %s%s += %s", name, dict(canon), value)
        return
    try:
        with _lock:
            c = _counters.get(name)
            if c is None:
                label_names = [k for k, _ in canon]
                c = Counter(name, name.replace("_", " "), label_names)
                _counters[name] = c
        if canon:
            c.labels(**dict(canon)).inc(value)
        else:
            c.inc(value)
    except Exception as e:  # pragma: no cover
        logger.debug("metrics counter prom error (%s): %s", name, e)


def gauge(
    name: str,
    labels: Mapping[str, str] | None = None,
    value: float = 0.0,
) -> None:
    canon = _canonical_labels(labels)
    key = (name, canon)
    with _lock:
        _gauge_values[key] = float(value)
    if not _HAS_PROM:
        logger.debug("metrics.gauge %s%s = %s", name, dict(canon), value)
        return
    try:
        with _lock:
            g = _gauges.get(name)
            if g is None:
                label_names = [k for k, _ in canon]
                g = Gauge(name, name.replace("_", " "), label_names)
                _gauges[name] = g
        if canon:
            g.labels(**dict(canon)).set(value)
        else:
            g.set(value)
    except Exception as e:  # pragma: no cover
        logger.debug("metrics gauge prom error (%s): %s", name, e)


def get_counter_value(
    name: str, labels: Mapping[str, str] | None = None
) -> float:
    return _counter_values.get((name, _canonical_labels(labels)), 0.0)


def get_gauge_value(
    name: str, labels: Mapping[str, str] | None = None
) -> float | None:
    return _gauge_values.get((name, _canonical_labels(labels)))


def reset_for_tests() -> None:
    """Drop the in-process mirror. Test-only helper."""
    with _lock:
        _counter_values.clear()
        _gauge_values.clear()


__all__ = [
    "counter",
    "gauge",
    "get_counter_value",
    "get_gauge_value",
    "reset_for_tests",
]
