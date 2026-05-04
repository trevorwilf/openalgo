"""T-31 — backend literal scanner audit.

Asserts ``scripts/audit/india_literal_scan_backend.py`` exits 0 on
the post-Phase-3 tree. The script's allowlist documents which
files are intentionally India-shaped (legacy India broker plugins,
sandbox providers, the v1 compat bridge alias map, etc.).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "india_literal_scan_backend.py"


def test_india_literal_scan_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, (
        f"india_literal_scan_backend exited {result.returncode}.\n"
        f"Output:\n{combined}"
    )
