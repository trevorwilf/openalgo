"""v6 Phase 2-bis options — dispatcher-caller migration contract."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# Options services migrated in Phase 2-bis options. Each service:
# (1) keeps its v3-vintage `is_india_region_active()` 422 gate;
# (2) calls `get_options_provider("india")` after passing the gate;
# (3) emits `OPTIONS_PROVIDER_NOT_REGISTERED` 503 if the provider is
#     not registered.
MIGRATED_SERVICES = [
    "services/expiry_service.py",
    "services/iv_chart_service.py",
    "services/option_greeks_service.py",
    "services/options_multiorder_service.py",
]


@pytest.mark.parametrize("path", MIGRATED_SERVICES)
def test_service_imports_options_dispatcher(path: str) -> None:
    text = _file_text(path)
    assert "from services.options.dispatcher import" in text, (
        f"{path}: must import the options dispatcher"
    )
    assert "get_options_provider(" in text, (
        f"{path}: must call get_options_provider"
    )


@pytest.mark.parametrize("path", MIGRATED_SERVICES)
def test_service_handles_options_provider_not_registered(path: str) -> None:
    text = _file_text(path)
    assert "OptionsProviderNotRegistered" in text, (
        f"{path}: must catch OptionsProviderNotRegistered"
    )
    assert "OPTIONS_PROVIDER_NOT_REGISTERED" in text, (
        f"{path}: must emit OPTIONS_PROVIDER_NOT_REGISTERED error code"
    )


def test_india_options_provider_is_registered() -> None:
    """The India options provider auto-registers at module import. The
    services above rely on this; the test is a sanity guard."""
    from services.options.dispatcher import get_options_provider

    provider = get_options_provider("india")
    assert provider.region_code == "india"
