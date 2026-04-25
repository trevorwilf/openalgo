"""Phase 8 — broker streaming registry.

Mirrors :mod:`services.broker_translator_registry`. Empty by default;
broker plugins register concrete :class:`BrokerMarketDataStream` and
:class:`BrokerOrderEventStream` implementations at startup.
"""

from __future__ import annotations

from domain.broker_streaming import (
    BrokerMarketDataStream,
    BrokerOrderEventStream,
)


_MARKET_DATA: dict[str, BrokerMarketDataStream] = {}
_ORDER_EVENTS: dict[str, BrokerOrderEventStream] = {}


def register_market_data_stream(stream: BrokerMarketDataStream) -> None:
    _MARKET_DATA[stream.broker_code.strip().lower()] = stream


def get_market_data_stream(broker_code: str) -> BrokerMarketDataStream | None:
    return _MARKET_DATA.get((broker_code or "").strip().lower())


def register_order_event_stream(stream: BrokerOrderEventStream) -> None:
    _ORDER_EVENTS[stream.broker_code.strip().lower()] = stream


def get_order_event_stream(broker_code: str) -> BrokerOrderEventStream | None:
    return _ORDER_EVENTS.get((broker_code or "").strip().lower())


def clear_streaming_registries_for_tests() -> None:
    _MARKET_DATA.clear()
    _ORDER_EVENTS.clear()


__all__ = [
    "clear_streaming_registries_for_tests",
    "get_market_data_stream",
    "get_order_event_stream",
    "register_market_data_stream",
    "register_order_event_stream",
]
