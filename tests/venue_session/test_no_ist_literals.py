"""New Phase 4 service modules must not hardcode 'Asia/Kolkata'.

Invariant #6: timezones come from the venue record. Legacy code can
keep its literals; the new service layer cannot.

The seed script is explicitly excluded — it embeds literal timezones
as reference data, which is correct.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Phase 4 service-layer files that must be free of "Asia/Kolkata" / "IST" literals.
NEW_SERVICE_FILES = [
    REPO_ROOT / "services" / "venue_session_service.py",
    REPO_ROOT / "database" / "venue_schedule_repo.py",
    REPO_ROOT / "upgrade" / "migrate_venue_schedule.py",
]


def _string_literals(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


@pytest.mark.parametrize("py_file", NEW_SERVICE_FILES)
def test_no_asia_kolkata_literal(py_file: Path) -> None:
    literals = _string_literals(py_file)
    assert not any("Asia/Kolkata" in s for s in literals), (
        f"{py_file.name}: contains Asia/Kolkata literal — new service code "
        "must read timezone from the venue record (invariant #6)"
    )


@pytest.mark.parametrize("py_file", NEW_SERVICE_FILES)
def test_no_bare_ist_word_in_code(py_file: Path) -> None:
    """'IST' as a bare word in string literals is also banned in new services."""
    for lit in _string_literals(py_file):
        # Allow anything that *mentions* IST inside a sentence/docstring
        # only when not being used as a value. This test is intentionally
        # permissive — it only rejects literal "IST" exactly.
        assert lit != "IST", (
            f"{py_file.name}: bare 'IST' string literal — new service code "
            "must read timezone from the venue record (invariant #6)"
        )
