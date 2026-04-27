"""Phase 2 v5 — backend contract test for the frontend literal scanner.

Runs ``npm run lint:literals`` from the backend test surface so that
backend CI catches frontend regressions even when only Python tests
are scheduled. The frontend scanner enforces v4 invariants 2 + 3
(no Asia/Kolkata or India-shaped literal in promoted frontend code).

The test skips gracefully if Node/npm or the frontend node_modules
are not installed (CI configures both; some local sandboxes may
not).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"


def _has_node() -> bool:
    return shutil.which("npm") is not None


def _has_node_modules() -> bool:
    return (FRONTEND_DIR / "node_modules").is_dir()


@pytest.mark.skipif(not _has_node(), reason="npm not on PATH")
@pytest.mark.skipif(not _has_node_modules(), reason="frontend/node_modules absent (run `npm install` first)")
def test_frontend_literal_scanner_clean():
    """`npm run lint:literals` must exit 0 with no India-literal violations."""
    # Windows: `npm` resolves to `npm.cmd`, which subprocess can only
    # execute when shell=True OR when the resolved path is passed
    # directly. We resolve via shutil.which then drop shell=False.
    npm_path = shutil.which("npm") or "npm"
    result = subprocess.run(
        [npm_path, "--prefix", str(FRONTEND_DIR), "run", "lint:literals"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        shell=False,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert result.returncode == 0, (
        f"frontend literal scanner failed (exit {result.returncode}):\n{combined}"
    )
    # Tolerate the npm noise lines but assert the success line is present.
    assert "no India-literal violations" in combined, (
        f"unexpected scanner output:\n{combined}"
    )
