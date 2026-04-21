"""Static guard: no module under domain/ may import from utils.constants.

Invariant #5 of the refactor playbook: "No new code may import
VALID_EXCHANGES, VALID_PRODUCT_TYPES, or VALID_PRICE_TYPES from
utils/constants.py." This test scans the domain package AST so
references inside docstrings or comments do not false-positive.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "domain"

BANNED_NAMES: frozenset[str] = frozenset(
    {"VALID_EXCHANGES", "VALID_PRODUCT_TYPES", "VALID_PRICE_TYPES"}
)


def _iter_domain_py_files() -> list[Path]:
    return sorted(p for p in DOMAIN_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_domain_dir_exists() -> None:
    assert DOMAIN_DIR.is_dir(), f"expected {DOMAIN_DIR} to exist"


@pytest.mark.parametrize("py_file", _iter_domain_py_files())
def test_no_utils_constants_import(py_file: Path) -> None:
    """No module under domain/ may import from utils.constants in any form."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("utils.constants"):
                pytest.fail(
                    f"{py_file.name}: `from {node.module} import ...` is banned "
                    "(invariant #5)"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("utils.constants"):
                    pytest.fail(
                        f"{py_file.name}: `import {alias.name}` is banned "
                        "(invariant #5)"
                    )


@pytest.mark.parametrize("py_file", _iter_domain_py_files())
def test_no_banned_name_reference(py_file: Path) -> None:
    """None of the banned legacy list names may appear as an identifier."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            pytest.fail(
                f"{py_file.name}:{node.lineno}: banned identifier "
                f"{node.id!r} (invariant #5)"
            )
