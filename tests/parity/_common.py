"""Shared setup for Phase 0 parity harnesses.

Each parity harness exercises a narrow slice of the current codebase with
fully-mocked external dependencies and writes its output to a JSON fixture.
The fixture is checked in; later phases run the same harness and diff
against the fixture to catch behavior drift in legacy Indian flows.

Importing this module has a side effect: it sets environment variables that
every `database/*.py` module reads at import time. Harnesses MUST import
this module before importing any project code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# Use an in-memory SQLite DB so harnesses never touch the user's real
# db/ files. Project database modules read DATABASE_URL at import time.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# These keys are required at import time by some modules. The parity
# harnesses never encrypt anything with them; dummy values are fine.
os.environ.setdefault("APP_KEY", "phase0-parity-harness-app-key-not-for-prod")
os.environ.setdefault("API_KEY_PEPPER", "phase0-parity-harness-pepper-not-for-prod")

# Ensure the repo root is on sys.path so `from services import ...` works
# regardless of where the harness is invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

BASELINE_DIR = Path(__file__).resolve().parent / "baseline"


def fixture_path(name: str) -> Path:
    """Resolve the JSON fixture path for a given harness name (no extension)."""
    return BASELINE_DIR / f"{name}.json"


def write_fixture(name: str, data: Dict[str, Any]) -> Path:
    """Write a fixture JSON file deterministically (sorted keys, stable indent)."""
    path = fixture_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def read_fixture(name: str) -> Dict[str, Any]:
    """Load a fixture JSON file. Raises FileNotFoundError if missing."""
    path = fixture_path(name)
    return json.loads(path.read_text(encoding="utf-8"))


def compare(expected: Any, actual: Any, path: str = "") -> List[str]:
    """Recursively diff two JSON-shaped values. Returns a list of mismatch strings."""
    errors: List[str] = []
    if type(expected) is not type(actual):
        # Treat int/float equivalently when numerically equal
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if expected != actual:
                errors.append(f"{path}: expected {expected!r}, got {actual!r}")
            return errors
        errors.append(
            f"{path}: type mismatch — expected {type(expected).__name__}, "
            f"got {type(actual).__name__}"
        )
        return errors
    if isinstance(expected, dict):
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        if missing:
            errors.append(f"{path}: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"{path}: unexpected keys {sorted(extra)}")
        for key in expected_keys & actual_keys:
            errors.extend(compare(expected[key], actual[key], f"{path}.{key}"))
        return errors
    if isinstance(expected, list):
        if len(expected) != len(actual):
            errors.append(f"{path}: length mismatch {len(expected)} vs {len(actual)}")
            return errors
        for i, (e, a) in enumerate(zip(expected, actual)):
            errors.extend(compare(e, a, f"{path}[{i}]"))
        return errors
    if expected != actual:
        errors.append(f"{path}: expected {expected!r}, got {actual!r}")
    return errors


def run_harness(
    name: str,
    generate: Callable[[], Dict[str, Any]],
    mode: str = "verify",
) -> Tuple[bool, List[str]]:
    """Run a harness in either 'generate' or 'verify' mode.

    generate: compute output, write to fixture.
    verify: compute output, compare to fixture, return (ok, errors).
    """
    actual = generate()
    if mode == "generate":
        write_fixture(name, actual)
        return True, [f"wrote {fixture_path(name)}"]
    try:
        expected = read_fixture(name)
    except FileNotFoundError:
        return False, [f"fixture missing: {fixture_path(name)} — run in generate mode first"]
    errors = compare(expected, actual)
    return (not errors), errors
