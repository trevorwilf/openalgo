"""Phase 1 — Datafeed Foundation: canonical interval vocabulary.

Distinct from the existing ``services.intervals_service`` which serves
the v1 lane by querying a broker's ``BrokerData.timeframe_map`` at
runtime. This module defines the *vocabulary* the chart UI shows, and
provides a translation map from canonical to broker-native tokens.

Vocabulary per HANDOFF D-08 — must stay aligned with
``frontend/src/charts/types/interval.ts``.
"""

from __future__ import annotations

from enum import Enum


class CanonicalInterval(str, Enum):
    """Canonical chart-interval vocabulary."""

    SEC_1 = "1s"
    SEC_5 = "5s"
    SEC_15 = "15s"
    SEC_30 = "30s"
    MIN_1 = "1m"
    MIN_2 = "2m"
    MIN_3 = "3m"
    MIN_5 = "5m"
    MIN_10 = "10m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    HOUR_1 = "1h"
    HOUR_2 = "2h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1mo"


CANONICAL_INTERVALS: tuple[str, ...] = tuple(i.value for i in CanonicalInterval)


# Broker-native translation map.
# Sourced from broker/<code>/api/data.py timeframe_map at the time of
# Phase 1; broker plugins remain the authoritative source.
ZERODHA_MAP: dict[str, str] = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1d": "day",
}

ALPACA_MAP: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "1d": "1Day",
    "1w": "1Week",
    "1mo": "1Month",
}

_BROKER_MAPS: dict[str, dict[str, str]] = {
    "zerodha": ZERODHA_MAP,
    "alpaca": ALPACA_MAP,
}


def is_canonical(interval: str) -> bool:
    """True iff `interval` is a canonical chart-interval token."""
    return interval in CANONICAL_INTERVALS


def translate_for_broker(interval: str, broker_code: str) -> str | None:
    """Translate a canonical interval to the broker's native token.

    Returns ``None`` when the broker does not support the interval.
    Broker codes are normalized to lowercase.
    """
    table = _BROKER_MAPS.get((broker_code or "").lower())
    if table is None:
        return None
    return table.get(interval)


def supported_for_broker(broker_code: str) -> list[str]:
    """All canonical intervals the named broker supports."""
    table = _BROKER_MAPS.get((broker_code or "").lower())
    if table is None:
        return []
    return [i for i in CANONICAL_INTERVALS if i in table]


__all__ = [
    "ALPACA_MAP",
    "CANONICAL_INTERVALS",
    "CanonicalInterval",
    "ZERODHA_MAP",
    "is_canonical",
    "supported_for_broker",
    "translate_for_broker",
]
