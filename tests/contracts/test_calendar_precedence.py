"""Phase 3 v4 (ADR 0024) — calendar precedence contract.

Promoted (non-India) market-data and order paths read calendar data
from ``database.venue_schedule_repo`` only. ``database.market_calendar_db``
is the legacy India source of truth and must never be imported by
PROMOTED_CORE files.

This test reads ``docs/refactor/file_classification.md`` for the
PROMOTED_CORE list and asserts that none of those files imports
``database.market_calendar_db`` at module load time.

The runtime import lock in
``tests/contracts/test_promoted_imports_runtime.py`` covers the
broader promoted lane; this test is the static AST guard with a
clearer error message.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION_DOC = REPO_ROOT / "docs" / "refactor" / "file_classification.md"


def _read_promoted_core_files() -> list[Path]:
    if not CLASSIFICATION_DOC.is_file():
        pytest.skip(
            "file_classification.md missing — run "
            "`uv run python scripts/audit/classify_files.py`."
        )
    in_section = False
    files: list[Path] = []
    for raw in CLASSIFICATION_DOC.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ") or line.startswith("### "):
            in_section = "PROMOTED_CORE" in line
            continue
        if not in_section:
            continue
        if line.startswith("- "):
            rel = line[2:].strip().strip("`")
            if rel:
                files.append(REPO_ROOT / rel)
    return files


def _imports_market_calendar_db(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return 0
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name == "database.market_calendar_db"
                    or alias.name.startswith("database.market_calendar_db.")
                ):
                    return node.lineno
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "database.market_calendar_db" or mod.startswith(
                "database.market_calendar_db."
            ):
                return node.lineno
    return 0


def test_no_promoted_core_file_imports_market_calendar_db() -> None:
    files = _read_promoted_core_files()
    assert files, "PROMOTED_CORE list missing — run classify_files.py."
    violations: list[str] = []
    for path in files:
        lineno = _imports_market_calendar_db(path)
        if lineno:
            rel = path.relative_to(REPO_ROOT).as_posix()
            violations.append(
                f"{rel}:{lineno}: PROMOTED_CORE file imports "
                "database.market_calendar_db — promoted code must read "
                "calendar data from database.venue_schedule_repo. "
                "See ADR 0024."
            )
    assert not violations, (
        "Calendar precedence violated:\n  " + "\n  ".join(violations)
    )
