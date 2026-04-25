"""Resolve a structured :class:`AccountContext` from auth + broker metadata.

Single entry point used by the v2 dispatcher. Future broker plugins
that need richer account information (Schwab account hashes, Webull
sub-accounts) override the pieces they care about by providing a
broker-specific resolver registered via
:func:`register_account_resolver`.
"""

from __future__ import annotations

from typing import Any, Callable

from domain.account_context import AccountContext
from domain.currency import Currency


# Per-broker resolver hooks. A broker that needs to translate auth_token
# into a multi-account or hash form registers itself here at startup.
_RESOLVERS: dict[str, Callable[[str, dict[str, Any]], AccountContext]] = {}


def register_account_resolver(
    broker_code: str,
    resolver: Callable[[str, dict[str, Any]], AccountContext],
) -> None:
    """Register a per-broker AccountContext resolver.

    The resolver takes ``(auth_token, broker_capabilities_dict)`` and
    returns an ``AccountContext``. Future Schwab / Webull plugins use
    this to map a session token into account hashes / sub-accounts.
    """
    _RESOLVERS[broker_code.strip().lower()] = resolver


def resolve_account_context(
    *,
    broker_code: str,
    auth_token: str,
    capabilities: Any | None = None,
) -> AccountContext:
    """Build an :class:`AccountContext` for the active request.

    Lookup order:

    1. Broker-specific resolver from :func:`register_account_resolver`.
    2. Default mapping: ``broker_code = broker_code``,
       ``account_id = auth_token`` (the legacy convention used by
       Phase 2 of the prior CC pass), ``base_currency`` from the
       broker's capabilities ``base_currency`` field if available.
    """
    code = (broker_code or "").strip().lower()
    resolver = _RESOLVERS.get(code)
    if resolver is not None:
        # Provide the resolver a plain dict snapshot so it never
        # accidentally mutates the cached BrokerCapabilities object.
        caps_payload: dict[str, Any] = {}
        if capabilities is not None and hasattr(capabilities, "model_dump"):
            caps_payload = capabilities.model_dump(mode="python")
        return resolver(auth_token, caps_payload)

    base_currency: Currency | None = None
    if capabilities is not None and getattr(capabilities, "base_currency", None):
        base_currency = capabilities.base_currency

    return AccountContext(
        broker_code=code,
        account_id=auth_token,
        base_currency=base_currency,
    )


def _reset_for_tests() -> None:
    _RESOLVERS.clear()


__all__ = [
    "register_account_resolver",
    "resolve_account_context",
]
