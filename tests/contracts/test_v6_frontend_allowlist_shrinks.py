"""Phase 1 v6 — frontend literal-scan allowlist guard.

Enforces the v6 containment perimeter for the frontend India-literal
scanner:

* The current allowlist is a **subset** of the Phase-1 baseline.
  Adding entries to the allowlist requires explicit baseline updates
  in a future v6 phase — this prevents silent regressions where a new
  page introduces an India literal that gets allowlisted out.
* The baseline fixture (`v6_phase_1_baseline_allowlist.json`) is
  captured at the start of Phase 1 from `dev` and committed alongside
  this test. Future v6 phases (1-bis, 2-bis-frontend) shrink the
  current allowlist further; they do not add to it.

The test does NOT require any specific entry to have been removed in
Phase 1 — Phase 1 ships the scaffolding (`useVenueTimezone` hook and
this guard); per-component cleanups are deferred to Phase 1-bis under
the v6 plan.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "tests" / "contracts" / "v6_phase_1_baseline_allowlist.json"
LIVE = REPO_ROOT / "frontend" / "scripts" / "literal_scan_allowlist.json"


def _paths(p: Path) -> set[str]:
    data = json.loads(p.read_text(encoding="utf-8"))
    return {entry["path"] for entry in data.get("allowlist", [])}


def test_baseline_fixture_exists() -> None:
    assert BASELINE.is_file(), (
        f"missing {BASELINE.relative_to(REPO_ROOT).as_posix()}"
    )


def test_live_allowlist_exists() -> None:
    assert LIVE.is_file(), (
        f"missing {LIVE.relative_to(REPO_ROOT).as_posix()}"
    )


def test_live_allowlist_is_subset_of_baseline() -> None:
    """Allowlist may shrink (entries removed during Phase 1 / 1-bis).
    Allowlist must NOT grow without an explicit baseline refresh."""
    baseline = _paths(BASELINE)
    live = _paths(LIVE)
    new_entries = live - baseline
    assert not new_entries, (
        f"v6 Phase 1 invariant violated: live allowlist contains "
        f"{len(new_entries)} entries not in the baseline. Adding "
        "entries requires bumping the v6 phase 1 baseline fixture: "
        f"{sorted(new_entries)}"
    )


def test_baseline_size_is_known() -> None:
    """Sanity check: the baseline size is the size we captured at the
    start of v6 Phase 1 (84 entries). If this trips, somebody changed
    the baseline fixture without updating this test — that almost
    always indicates an accidental allowlist addition."""
    paths = _paths(BASELINE)
    assert len(paths) == 84, (
        f"baseline size changed unexpectedly; expected 84, got {len(paths)}"
    )
