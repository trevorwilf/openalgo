"""v6 Phase 2-bis screener — dispatcher-caller migration contract."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_chartink_blueprint_imports_screener_dispatcher() -> None:
    text = _file_text("market_regions/india/legacy_v1/blueprints/chartink.py")
    assert "from services.screeners.dispatcher import" in text
    assert 'get_screener_provider("chartink")' in text


def test_chartink_blueprint_handles_screener_provider_not_registered() -> None:
    text = _file_text("market_regions/india/legacy_v1/blueprints/chartink.py")
    assert "ScreenerProviderNotRegistered" in text
    assert "screener_provider_not_registered" in text


def test_chartink_provider_is_registered() -> None:
    """The Chartink screener provider auto-registers at module import."""
    from services.screeners.dispatcher import get_screener_provider

    provider = get_screener_provider("chartink")
    assert provider.provider_code == "chartink"
    assert provider.region_code == "india"
