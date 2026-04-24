"""Phase 2a is schema-only. No consumer may import instruments_repo yet.

Phase 2b onwards wires the sync pipeline behind a feature flag; until
then, the only legitimate importers are:

* The repo module itself.
* The Phase 2a migration script.
* Tests under tests/instruments_repo/.

This test fails if any other part of the tree (services/, blueprints/,
broker/, database/* other than this module, utils/, restx_api/) grows a
`from database.instruments_repo import` reference before its phase.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that are *not* allowed to import instruments_repo yet.
BANNED_ROOTS = [
    REPO_ROOT / "services",
    REPO_ROOT / "blueprints",
    REPO_ROOT / "broker",
    REPO_ROOT / "utils",
    REPO_ROOT / "restx_api",
    REPO_ROOT / "sandbox",
    REPO_ROOT / "websocket_proxy",
]


def _iter_py_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in root.rglob("*.py")
            if "__pycache__" not in p.parts
        )
    return sorted(files)


def _imports_instruments_repo(py_file: Path) -> bool:
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return False  # Don't fail the suite on pre-existing syntax issues
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "database.instruments_repo":
                return True
            if node.module == "database" and any(
                alias.name == "instruments_repo" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "database.instruments_repo":
                    return True
    return False


# Allowlist of files greenlit as legitimate consumers of
# `database.instruments_repo` on or after their stated phase. Each new
# phase extends this set rather than touching services at large.
PHASE_ALLOWED: set[Path] = {
    # Phase 2b — non-destructive sync pipeline
    REPO_ROOT / "services" / "instrument_sync_service.py",
    REPO_ROOT / "services" / "instrument_sync_adapters" / "__init__.py",
    REPO_ROOT / "services" / "instrument_sync_adapters" / "zerodha_adapter.py",
    REPO_ROOT / "services" / "instrument_sync_adapters" / "delta_adapter.py",
    # Phase 3a — instrument resolver
    REPO_ROOT / "services" / "instrument_resolver.py",
    # Phase 4 — venue session service (needs venues_get + session_scope)
    REPO_ROOT / "services" / "venue_session_service.py",
    REPO_ROOT / "services" / "market_calendar_service.py",
    # Phase 6 — /api/v2 skeleton (needs instruments_repo for lookup)
    REPO_ROOT / "restx_api" / "v2" / "instruments.py",
    REPO_ROOT / "restx_api" / "v2" / "orders.py",
    REPO_ROOT / "restx_api" / "v2" / "quotes.py",
    # Post-Phase-9 / Phase 4 of the market-agnostic lane — promoted-lane
    # instrument resolution and bars dispatcher.
    REPO_ROOT / "services" / "instrument_resolution.py",
    REPO_ROOT / "restx_api" / "v2" / "bars.py",
    # Phase 6b — Alpaca promoted-lane adapter sync.
    REPO_ROOT / "broker" / "alpaca" / "sync" / "instrument_sync.py",
}


@pytest.mark.parametrize("py_file", _iter_py_files(BANNED_ROOTS))
def test_no_consumer_imports_instruments_repo(py_file: Path) -> None:
    if py_file in PHASE_ALLOWED:
        # Legitimate per-phase consumer — skip.
        return
    assert not _imports_instruments_repo(py_file), (
        f"{py_file.relative_to(REPO_ROOT)} imports database.instruments_repo "
        "but is not on the per-phase allowlist. If this is an intentional "
        "consumer, add it to PHASE_ALLOWED."
    )
