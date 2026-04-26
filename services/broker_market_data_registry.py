"""Registries for promoted-lane account / market data adapters.

Parallel to :mod:`services.broker_translator_registry`. Holds the
:class:`BrokerQuoteAdapter`, :class:`BrokerBarAdapter`,
:class:`BrokerPositionAdapter`, and :class:`BrokerBalanceAdapter`
registries used by the v2 read-side dispatch path. Phase 5 v4 added
the position + balance registries; the v2 routes fail-closed when a
non-India broker has no adapter registered for the requested feature.
"""

from __future__ import annotations

from domain.broker_market_data import (
    BrokerBalanceAdapter,
    BrokerBarAdapter,
    BrokerPositionAdapter,
    BrokerQuoteAdapter,
)

_QUOTE_REGISTRY: dict[str, BrokerQuoteAdapter] = {}
_BAR_REGISTRY: dict[str, BrokerBarAdapter] = {}
_POSITION_REGISTRY: dict[str, BrokerPositionAdapter] = {}
_BALANCE_REGISTRY: dict[str, BrokerBalanceAdapter] = {}


def register_broker_quote_adapter(adapter: BrokerQuoteAdapter) -> None:
    _QUOTE_REGISTRY[adapter.broker_code.lower()] = adapter


def register_broker_bar_adapter(adapter: BrokerBarAdapter) -> None:
    _BAR_REGISTRY[adapter.broker_code.lower()] = adapter


def register_broker_position_adapter(adapter: BrokerPositionAdapter) -> None:
    _POSITION_REGISTRY[adapter.broker_code.lower()] = adapter


def register_broker_balance_adapter(adapter: BrokerBalanceAdapter) -> None:
    _BALANCE_REGISTRY[adapter.broker_code.lower()] = adapter


def get_broker_quote_adapter(broker_code: str) -> BrokerQuoteAdapter | None:
    if not broker_code:
        return None
    return _QUOTE_REGISTRY.get(broker_code.lower())


def get_broker_bar_adapter(broker_code: str) -> BrokerBarAdapter | None:
    if not broker_code:
        return None
    return _BAR_REGISTRY.get(broker_code.lower())


def get_broker_position_adapter(broker_code: str) -> BrokerPositionAdapter | None:
    if not broker_code:
        return None
    return _POSITION_REGISTRY.get(broker_code.lower())


def get_broker_balance_adapter(broker_code: str) -> BrokerBalanceAdapter | None:
    if not broker_code:
        return None
    return _BALANCE_REGISTRY.get(broker_code.lower())


def clear_market_data_registries_for_tests() -> None:
    _QUOTE_REGISTRY.clear()
    _BAR_REGISTRY.clear()
    _POSITION_REGISTRY.clear()
    _BALANCE_REGISTRY.clear()


__all__ = [
    "clear_market_data_registries_for_tests",
    "get_broker_balance_adapter",
    "get_broker_bar_adapter",
    "get_broker_position_adapter",
    "get_broker_quote_adapter",
    "register_broker_balance_adapter",
    "register_broker_bar_adapter",
    "register_broker_position_adapter",
    "register_broker_quote_adapter",
]
