"""Phase 8 v4 (ADR 0026) — Sandbox provider dispatcher.

Resolves the active broker → region → registered :class:`SandboxProvider`.
Fail-closed: if no provider is registered for the active region, the
caller receives a structured ``SandboxProviderNotRegistered`` error
that maps to the v2 API's ``503 sandbox_provider_not_registered``.

Phase 8 ships the dispatcher + India + US provider auto-registration.
The wiring of ``blueprints/sandbox.py`` to call the dispatcher is the
focused Phase 8-bis follow-up; until then the existing India sandbox
blueprint paths continue to work directly (parity-protected).
"""

from __future__ import annotations

from domain.errors import DomainError, ErrorCode
from services.sandbox.providers.base import SandboxProvider
from services.sandbox.providers.eu import EUSandboxProvider
from services.sandbox.providers.india import IndiaSandboxProvider
from services.sandbox.providers.uk import UKSandboxProvider
from services.sandbox.providers.us import USSandboxProvider
from utils.logging import get_logger

logger = get_logger(__name__)


_REGISTRY: dict[str, SandboxProvider] = {}


class SandboxProviderNotRegistered(DomainError):
    code = ErrorCode.SANDBOX_PROVIDER_NOT_REGISTERED

    def __init__(self, region_code: str) -> None:
        self.region_code = region_code
        super().__init__(
            f"No sandbox provider registered for region {region_code!r}; "
            "the sandbox feature is unavailable for this broker. See "
            "ADR 0026."
        )


def register_sandbox_provider(provider: SandboxProvider) -> None:
    code = str(provider.region_code).strip().lower()
    _REGISTRY[code] = provider
    logger.debug("Registered sandbox provider for region %r", code)


def get_sandbox_provider(region_code: str) -> SandboxProvider:
    code = str(region_code).strip().lower()
    provider = _REGISTRY.get(code)
    if provider is None:
        raise SandboxProviderNotRegistered(code)
    return provider


def get_sandbox_provider_or_none(region_code: str) -> SandboxProvider | None:
    return _REGISTRY.get(str(region_code).strip().lower())


def clear_sandbox_registry_for_tests() -> None:
    _REGISTRY.clear()


def install_default_sandbox_providers() -> None:
    """Register the India + US providers shipped in v4 plus the EU +
    UK stubs added in v6 Phase 3."""
    register_sandbox_provider(IndiaSandboxProvider())
    register_sandbox_provider(USSandboxProvider())
    register_sandbox_provider(EUSandboxProvider())
    register_sandbox_provider(UKSandboxProvider())


# Auto-install at import time so the dispatcher is usable as soon as
# the module loads. Tests that want a clean state call
# clear_sandbox_registry_for_tests().
install_default_sandbox_providers()


__all__ = [
    "SandboxProviderNotRegistered",
    "clear_sandbox_registry_for_tests",
    "get_sandbox_provider",
    "get_sandbox_provider_or_none",
    "install_default_sandbox_providers",
    "register_sandbox_provider",
]
