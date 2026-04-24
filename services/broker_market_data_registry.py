"""Registries for :class:`BrokerQuoteAdapter` and :class:`BrokerBarAdapter`.

Parallel to :mod:`services.broker_translator_registry`.
"""

from __future__ import annotations

from domain.broker_market_data import BrokerBarAdapter, BrokerQuoteAdapter

_QUOTE_REGISTRY: dict[str, BrokerQuoteAdapter] = {}
_BAR_REGISTRY: dict[str, BrokerBarAdapter] = {}


def register_broker_quote_adapter(adapter: BrokerQuoteAdapter) -> None:
    _QUOTE_REGISTRY[adapter.broker_code.lower()] = adapter


def register_broker_bar_adapter(adapter: BrokerBarAdapter) -> None:
    _BAR_REGISTRY[adapter.broker_code.lower()] = adapter


def get_broker_quote_adapter(broker_code: str) -> BrokerQuoteAdapter | None:
    if not broker_code:
        return None
    return _QUOTE_REGISTRY.get(broker_code.lower())


def get_broker_bar_adapter(broker_code: str) -> BrokerBarAdapter | None:
    if not broker_code:
        return None
    return _BAR_REGISTRY.get(broker_code.lower())


def clear_market_data_registries_for_tests() -> None:
    _QUOTE_REGISTRY.clear()
    _BAR_REGISTRY.clear()


__all__ = [
    "clear_market_data_registries_for_tests",
    "get_broker_bar_adapter",
    "get_broker_quote_adapter",
    "register_broker_bar_adapter",
    "register_broker_quote_adapter",
]
