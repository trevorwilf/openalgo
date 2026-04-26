"""Phase 10 v4 (ADR 0028) — Screener provider dispatcher."""

from __future__ import annotations

from domain.errors import DomainError, ErrorCode
from services.screeners.providers.base import ScreenerProvider
from services.screeners.providers.india import ChartinkScreenerProvider
from utils.logging import get_logger

logger = get_logger(__name__)

_REGISTRY: dict[str, ScreenerProvider] = {}


class ScreenerProviderNotRegistered(DomainError):
    code = ErrorCode.SCREENER_PROVIDER_NOT_REGISTERED

    def __init__(self, provider_code: str) -> None:
        self.provider_code = provider_code
        super().__init__(
            f"No screener provider registered for {provider_code!r}; "
            "the screener feature is unavailable. See ADR 0028."
        )


def register_screener_provider(provider: ScreenerProvider) -> None:
    code = str(provider.provider_code).strip().lower()
    _REGISTRY[code] = provider
    logger.debug("Registered screener provider %r (region=%r)", code, provider.region_code)


def get_screener_provider(provider_code: str) -> ScreenerProvider:
    code = str(provider_code).strip().lower()
    provider = _REGISTRY.get(code)
    if provider is None:
        raise ScreenerProviderNotRegistered(code)
    return provider


def get_screener_provider_or_none(provider_code: str) -> ScreenerProvider | None:
    return _REGISTRY.get(str(provider_code).strip().lower())


def clear_screener_registry_for_tests() -> None:
    _REGISTRY.clear()


def install_default_screener_providers() -> None:
    register_screener_provider(ChartinkScreenerProvider())


install_default_screener_providers()


__all__ = [
    "ScreenerProviderNotRegistered",
    "clear_screener_registry_for_tests",
    "get_screener_provider",
    "get_screener_provider_or_none",
    "install_default_screener_providers",
    "register_screener_provider",
]
