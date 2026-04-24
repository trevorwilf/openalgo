"""Registry for per-broker :class:`BrokerOrderTranslator` instances.

Promoted brokers register their translator at app startup. The
``/api/v2/orders`` dispatcher looks up a translator by ``broker_code``
when the per-broker flag ``API_V2_<BROKER_CODE_UPPER>`` is set; if no
translator is registered, the route returns 503.

Thread-safety is not required: registration is a one-shot startup
event. Lookups are reads of a module-level dict.
"""

from __future__ import annotations

from domain.broker_translator import BrokerOrderTranslator

_REGISTRY: dict[str, BrokerOrderTranslator] = {}


def register_broker_translator(translator: BrokerOrderTranslator) -> None:
    """Register ``translator`` under ``translator.broker_code``.

    Re-registering an existing code overwrites the prior entry — this
    is intentional so tests can swap in a fake without clearing the
    registry first. App startup registers each broker exactly once.
    """
    code = translator.broker_code.lower()
    _REGISTRY[code] = translator


def get_broker_translator(broker_code: str) -> BrokerOrderTranslator | None:
    """Return the registered translator for ``broker_code``, or None."""
    if not broker_code:
        return None
    return _REGISTRY.get(broker_code.lower())


def clear_registry_for_tests() -> None:
    """Clear the registry. Test-only helper."""
    _REGISTRY.clear()


__all__ = [
    "register_broker_translator",
    "get_broker_translator",
    "clear_registry_for_tests",
]
