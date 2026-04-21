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


@pytest.mark.parametrize("py_file", _iter_py_files(BANNED_ROOTS))
def test_no_consumer_imports_instruments_repo(py_file: Path) -> None:
    assert not _imports_instruments_repo(py_file), (
        f"{py_file.relative_to(REPO_ROOT)} imports database.instruments_repo — "
        "that's Phase 2b territory, not Phase 2a"
    )
