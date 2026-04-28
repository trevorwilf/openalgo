"""Phase 9 v4 (ADR 0027) — Options provider dispatcher."""

from __future__ import annotations

from domain.errors import DomainError, ErrorCode
from services.options.providers.base import OptionsProvider
from services.options.providers.eu import EUOptionsProvider
from services.options.providers.india import IndiaOptionsProvider
from services.options.providers.uk import UKOptionsProvider
from services.options.providers.us import USOptionsProvider
from utils.logging import get_logger

logger = get_logger(__name__)


_REGISTRY: dict[str, OptionsProvider] = {}


class OptionsProviderNotRegistered(DomainError):
    code = ErrorCode.OPTIONS_PROVIDER_NOT_REGISTERED

    def __init__(self, region_code: str) -> None:
        self.region_code = region_code
        super().__init__(
            f"No options provider registered for region {region_code!r}; "
            "options analytics are unavailable for this broker. See ADR 0027."
        )


def register_options_provider(provider: OptionsProvider) -> None:
    code = str(provider.region_code).strip().lower()
    _REGISTRY[code] = provider
    logger.debug("Registered options provider for region %r", code)


def get_options_provider(region_code: str) -> OptionsProvider:
    code = str(region_code).strip().lower()
    provider = _REGISTRY.get(code)
    if provider is None:
        raise OptionsProviderNotRegistered(code)
    return provider


def get_options_provider_or_none(region_code: str) -> OptionsProvider | None:
    return _REGISTRY.get(str(region_code).strip().lower())


def clear_options_registry_for_tests() -> None:
    _REGISTRY.clear()


def install_default_options_providers() -> None:
    register_options_provider(IndiaOptionsProvider())
    register_options_provider(USOptionsProvider())
    register_options_provider(EUOptionsProvider())
    register_options_provider(UKOptionsProvider())


install_default_options_providers()


__all__ = [
    "OptionsProviderNotRegistered",
    "clear_options_registry_for_tests",
    "get_options_provider",
    "get_options_provider_or_none",
    "install_default_options_providers",
    "register_options_provider",
]
