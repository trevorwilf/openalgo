"""v4 invariant 1 — no silent India fallback in promoted code.

Promoted code must not default to ``"india"`` when region context is
missing. Missing region context is a structured error, not a silent
fallback. The literal scanner already blocks the *string* ``"india"``
in promoted code as part of the broader India-literal scan; this test
adds the more specific contract: any module-level constant whose name
ends in ``_FALLBACK_REGION``, ``FALLBACK_REGION_CODE``, or
``DEFAULT_REGION_*`` and whose value is ``"india"`` (case-insensitive)
is a violation in PROMOTED_CORE.

Phase 2 of v4 removed both legacy fallback constants
(``_FALLBACK_REGION`` in ``services/feature_gate_service.py`` and
``FALLBACK_REGION_CODE`` in ``services/market_region_service.py``).
This test now guards against any regression.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION_DOC = REPO_ROOT / "docs" / "refactor" / "file_classification.md"


SUSPECT_NAME_FRAGMENTS: tuple[str, ...] = (
    "FALLBACK_REGION",
    "DEFAULT_REGION",
    "FALLBACK_REGION_CODE",
)


def _read_promoted_core_files() -> list[Path]:
    """Parse ``file_classification.md`` and return PROMOTED_CORE paths."""
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


def _suspect_assigns(tree: ast.Module) -> Iterable[tuple[str, str, int]]:
    """Yield (name, value, lineno) for module-level string assigns whose
    target name contains a suspect fragment."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = [
                t.id for t in node.targets if isinstance(t, ast.Name)
            ]
            if not target_names:
                continue
            if not any(
                any(frag in name for frag in SUSPECT_NAME_FRAGMENTS)
                for name in target_names
            ):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                for name in target_names:
                    yield name, node.value.value, node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if not any(frag in name for frag in SUSPECT_NAME_FRAGMENTS):
                continue
            if (
                node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                yield name, node.value.value, node.lineno


def _check_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel}: could not read: {exc}"]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    violations: list[str] = []
    for name, value, lineno in _suspect_assigns(tree):
        if value.strip().lower() == "india":
            violations.append(
                f"{rel}:{lineno}: PROMOTED_CORE module sets {name}={value!r} "
                "— missing region context must be a structured error, not a "
                "silent India fallback. See ADR 0023, v4 invariant 1."
            )
    return violations


def test_no_silent_india_fallback_in_promoted_core() -> None:
    files = _read_promoted_core_files()
    assert files, "PROMOTED_CORE list missing — run classify_files.py."
    violations: list[str] = []
    for path in files:
        violations.extend(_check_file(path))
    assert not violations, (
        "v4 invariant 1 violated — silent India fallbacks in promoted core:\n  "
        + "\n  ".join(violations)
    )
