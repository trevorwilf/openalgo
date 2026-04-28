"""Phase 0 v6 — gap inventory contract.

Asserts the Phase 0 deliverable is on disk and structured per the
v6 prompt's requirements:

* The inventory file exists at the expected path.
* It contains the four required section headings.
* Every GENUINE-GAP row in the per-finding classification table
  carries a non-empty owning-phase value.

The contract is intentionally lightweight — Phase 0 is read-only by
design. Subsequent phases close the gaps the inventory enumerates;
each of those phases ships its own contract tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "docs" / "refactor" / "v6_gap_inventory.md"

REQUIRED_SECTIONS = (
    "Per-finding classification table",
    "Mock plugin extension list (for Phase 4)",
    "Legacy-compat named-caller list (for Phase 2)",
    "Frontend per-component cleanup list (for Phase 1)",
)


@pytest.fixture(scope="module")
def inventory_text() -> str:
    assert INVENTORY_PATH.is_file(), (
        f"missing {INVENTORY_PATH.relative_to(REPO_ROOT).as_posix()} — "
        "Phase 0 of the v6 refactor must produce this inventory"
    )
    return INVENTORY_PATH.read_text(encoding="utf-8")


def test_inventory_file_exists(inventory_text: str) -> None:
    # Inventory must be non-trivial — under 2 KB strongly implies it
    # was stubbed without the four required sections.
    assert len(inventory_text) > 2048, (
        f"inventory is suspiciously short ({len(inventory_text)} bytes)"
    )


@pytest.mark.parametrize("heading", REQUIRED_SECTIONS)
def test_inventory_has_required_section(inventory_text: str, heading: str) -> None:
    assert heading in inventory_text, (
        f"inventory missing required section heading: {heading!r}"
    )


_TABLE_ROW = re.compile(r"^\|\s*[A-Z]\d+-\d+-\d+\s*\|", re.MULTILINE)


def test_inventory_per_finding_table_has_rows(inventory_text: str) -> None:
    rows = _TABLE_ROW.findall(inventory_text)
    # Two experts × two appendix sections × ~50 rows each ≈ 200; at a
    # bare minimum we want a few dozen rows so the table is real.
    assert len(rows) >= 50, (
        f"inventory per-finding table should have >= 50 IDs; got {len(rows)}"
    )


_GAP_ROW = re.compile(
    r"^\|\s*[A-Z]\d+-\d+-\d+\s*\|[^|]*\|\s*GENUINE-GAP\s*\|\s*([^|]*)\|",
    re.MULTILINE,
)


def test_every_genuine_gap_row_has_owning_phase(inventory_text: str) -> None:
    """If the inventory marks any row as GENUINE-GAP, the owning-phase
    column must be non-empty. (Phase 0 itself may classify everything as
    ALREADY-CLOSED / BIS-DEFERRED / OUT-OF-SCOPE / INTENTIONAL-INDIA-LIMIT,
    in which case this test passes vacuously — that is the intended
    Phase 0 outcome on the v6 dev tip.)"""
    matches = _GAP_ROW.findall(inventory_text)
    for owning_phase in matches:
        cleaned = owning_phase.strip()
        assert cleaned and cleaned not in {"-", "n/a", "N/A", "TODO", "?"}, (
            "GENUINE-GAP row has empty/placeholder owning-phase column"
        )
