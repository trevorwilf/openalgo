"""Phase 6 — P-04: display tree and execution tree share NO mutable state.

The contract is enforced via static-import inspection over the
`frontend/src/charts/{display,execution}/*` source files. Display
files must NOT import from `../execution/*`, and vice versa. Both
trees may import from the workspace store, types/, and engine
loader, but neither imports from the other.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DISPLAY_DIR = REPO_ROOT / "frontend" / "src" / "charts" / "display"
EXECUTION_DIR = REPO_ROOT / "frontend" / "src" / "charts" / "execution"


def _read_files(d: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    out = []
    if not d.exists():
        return out
    for ext in ("*.ts", "*.tsx"):
        for f in d.rglob(ext):
            if "__tests__" in f.parts:
                continue
            out.append((f, f.read_text(encoding="utf-8")))
    return out


def test_display_tree_does_not_import_execution_modules():
    for path, src in _read_files(DISPLAY_DIR):
        assert not re.search(r"from\s+['\"][^'\"]*\bexecution\b[^'\"]*['\"]", src), (
            f"{path}: display tree imports execution module"
        )


def test_execution_tree_does_not_import_display_modules():
    for path, src in _read_files(EXECUTION_DIR):
        assert not re.search(r"from\s+['\"][^'\"]*\bdisplay\b[^'\"]*['\"]", src), (
            f"{path}: execution tree imports display module"
        )


def test_display_tree_has_at_least_one_file():
    files = _read_files(DISPLAY_DIR)
    # Phase 6 ships OrderOverlayLayer + StrategySignalLayer (+ index.ts).
    assert any(p.name != "index.ts" for p, _ in files), (
        "Phase 6 should ship at least one display-tree component"
    )


def test_execution_tree_has_at_least_one_file():
    files = _read_files(EXECUTION_DIR)
    assert any(p.name != "index.ts" for p, _ in files), (
        "Phase 6 should ship at least one execution-tree component"
    )
