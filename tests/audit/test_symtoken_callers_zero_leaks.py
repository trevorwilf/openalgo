"""Phase 3 v3 / ADR 0019 — assert the SymToken caller audit reports
zero ``PROMOTED_LEAK`` rows.

The script ``scripts/audit/symtoken_callers.py`` walks the source
tree, collects every file that imports from ``database.symbol`` /
``database.token_db_enhanced``, and classifies each caller via the
Phase 0 file_classification report. Any caller that the classifier
labels ``PROMOTED_CORE`` is a leak — the lane-isolation contract
forbids PROMOTED_CORE files from depending on the legacy SymToken
surface.

This test parses the generated report and asserts the leak section
is empty. CI re-runs the audit (it's idempotent) so the report on
disk is fresh.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs" / "refactor" / "symtoken_callers.md"


def _ensure_report_fresh() -> None:
    """Regenerate the audit report in-process so the test sees the
    current state, not a stale committed snapshot."""
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "audit"))
    try:
        import symtoken_callers  # type: ignore[import-not-found]

        bucket, _classification = symtoken_callers.audit()
        text = symtoken_callers.render(bucket)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text, encoding="utf-8")
    finally:
        sys.path.pop(0)


def _parse_leak_section() -> list[str]:
    text = REPORT.read_text(encoding="utf-8")
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().startswith("PROMOTED_LEAK")
            continue
        if in_section and line.startswith("- `"):
            # `path` — imports: ...
            out.append(line)
    return out


def test_symtoken_audit_report_exists() -> None:
    _ensure_report_fresh()
    assert REPORT.is_file()


def test_symtoken_audit_zero_promoted_leaks() -> None:
    _ensure_report_fresh()
    leaks = _parse_leak_section()
    assert not leaks, (
        "PROMOTED_CORE files import SymToken / token_db_enhanced — "
        "Phase 3 v3 (ADR 0019) requires zero leaks:\n  "
        + "\n  ".join(leaks)
    )
