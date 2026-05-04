"""T-32 — broker capability drift scan audit.

Asserts ``scripts/audit/broker_capability_drift_scan.py`` exits 0
on the current set of broker plugins.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "broker_capability_drift_scan.py"


def test_broker_capability_drift_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, (
        f"broker_capability_drift_scan exited {result.returncode}.\n"
        f"Output:\n{combined}"
    )
