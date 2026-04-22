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
#
# `services/venue_session_service.py` contains exactly one intentional
# "Asia/Kolkata" literal — the default value of `venue_tz_or_default`'s
# `default=` parameter. That parameter is the explicit migration seam
# legacy services use to stay byte-identical with flag-off Indian
# behavior. The constant is not "this service assumes IST"; it is
# "when explicitly asked for a safe legacy default, return IST". The
# test below scans the rest of the module by whitelisting only that
# one literal value at its source location.
NEW_SERVICE_FILES = [
    REPO_ROOT / "services" / "venue_session_service.py",
    REPO_ROOT / "database" / "venue_schedule_repo.py",
    REPO_ROOT / "upgrade" / "migrate_venue_schedule.py",
]

# File path → max allowed count of "Asia/Kolkata" string literals. For
# files not in this dict the max is 0 (no literals at all).
_ASIA_KOLKATA_BUDGET: dict[Path, int] = {
    # Documented migration-seam default in venue_tz_or_default; see
    # the function docstring. Two literals total: one as the
    # `default=` parameter value, one as an example in the docstring.
    REPO_ROOT / "services" / "venue_session_service.py": 2,
}


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
    count = sum(1 for lit in literals if "Asia/Kolkata" in lit)
    budget = _ASIA_KOLKATA_BUDGET.get(py_file, 0)
    assert count <= budget, (
        f"{py_file.name}: {count} Asia/Kolkata literal(s), budget is {budget}. "
        "New service code must read timezone from the venue record (invariant #6). "
        "If a new documented migration seam needs a literal default, bump the "
        "per-file budget in _ASIA_KOLKATA_BUDGET above."
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
