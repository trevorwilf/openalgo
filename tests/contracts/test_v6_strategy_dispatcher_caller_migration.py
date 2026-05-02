"""v6 Phase 2-bis strategy — venue-session integration contract."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_flow_executor_imports_venue_session_helper() -> None:
    """flow_executor_service imports the venue tz helper. Phase 2-bis
    landed the import; Phase 2-bis-2 migrates the per-default literal
    sites to use venue-derived timezone/sessions."""
    text = _file_text(
        "market_regions/india/legacy_v1/services/flow_executor_service.py"
    )
    assert "from services.venue_session_service import venue_tz_or_default" in text
    assert "venue_tz_or_default(" in text


def test_venue_tz_or_default_for_nse_returns_india_timezone() -> None:
    """The NSE venue resolves to Asia/Kolkata bit-identically — the
    flow executor migration is value-preserving for India users."""
    from services.venue_session_service import venue_tz_or_default

    assert venue_tz_or_default("NSE") == "Asia/Kolkata"
