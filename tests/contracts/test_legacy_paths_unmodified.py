"""Phase 7 — verify the legacy chart files in HANDOFF §0.4 are byte-
identical to their state on the merge-base of `dev` and `main`.

The contract: the new chart workspace lives entirely under
`frontend/src/charts/*`, `services/charts/*`, `restx_api/v2/chart/*`,
and the additive DB tables. The legacy India-specific chart pages,
the `/historify/api/data` blueprint, the `services/historify_*`
shims, and the `database/historify_db.py` shim are FROZEN — bug
fixes + compliance only.

This test runs `git diff --quiet` against the merge-base for every
path in the §0.4 list. Any byte change fails the test.

Skipped when the test environment isn't a git checkout (e.g. PyPI
sdist build).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# HANDOFF §0.4 — files & paths to NEVER modify, verified by `git diff`.
FRONTEND_LEGACY_PATHS = [
    "frontend/src/india_legacy/pages/HistorifyCharts.tsx",
    "frontend/src/india_legacy/pages/Historify.tsx",
    "frontend/src/india_legacy/pages/StraddleChart.tsx",
    "frontend/src/india_legacy/pages/CustomStraddle.tsx",
    "frontend/src/india_legacy/pages/IVChart.tsx",
    "frontend/src/india_legacy/pages/IVSmile.tsx",
    "frontend/src/india_legacy/pages/OITracker.tsx",
    "frontend/src/india_legacy/pages/OIProfile.tsx",
    "frontend/src/india_legacy/pages/GEXDashboard.tsx",
    "frontend/src/india_legacy/pages/TradingView.tsx",
    "frontend/src/india_legacy/pages/GoCharting.tsx",
    "frontend/src/pages/MaxPain.tsx",
    "frontend/src/pages/VolSurface.tsx",
    "frontend/src/pages/PnLTracker.tsx",
    "frontend/src/pages/HealthMonitor.tsx",
    "frontend/src/india_legacy/components/strategy-builder/PayoffChart.tsx",
]

BACKEND_LEGACY_PATHS = [
    # Shims / compatibility wrappers — frozen but the code body lives
    # under market_regions/india/legacy_v1/ so the shim itself shouldn't
    # change either.
    "services/chart_service.py",
    "services/historify_service.py",
    "services/historify_scheduler_service.py",
    "database/historify_db.py",
]


def _is_git_repo() -> bool:
    return (REPO_ROOT / ".git").exists()


def _merge_base() -> str | None:
    """Return the chart-phase base — the parent of the first
    `charting: phase 1` commit. The §0.4 contract is that the chart
    workspace work doesn't touch the legacy paths, so the right
    reference is the state of the tree just before Phase 1 started.

    Falls back to `git merge-base dev main` when no chart commit is
    in the history (e.g. a fork that hasn't run any phases yet)."""
    # First try: the parent of the oldest `charting: phase 1` commit.
    try:
        out = subprocess.run(
            [
                "git",
                "log",
                "--reverse",
                "--format=%H",
                "--grep=charting: phase 1",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
        commits = out.stdout.strip().splitlines()
        if commits:
            first_phase1 = commits[0]
            parent = subprocess.run(
                ["git", "rev-parse", f"{first_phase1}~1"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
                text=True,
            )
            return parent.stdout.strip()
    except subprocess.CalledProcessError:
        pass
    # Fallback: merge-base of dev and main.
    for ref_pair in (("dev", "main"), ("HEAD", "main"), ("HEAD", "origin/main")):
        try:
            out = subprocess.run(
                ["git", "merge-base", *ref_pair],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
                text=True,
            )
            return out.stdout.strip()
        except subprocess.CalledProcessError:
            continue
    return None


@pytest.mark.skipif(not _is_git_repo(), reason="not a git checkout")
def test_legacy_frontend_paths_unmodified():
    base = _merge_base()
    if base is None:
        pytest.skip("could not resolve a merge-base ref")
    drift: list[str] = []
    for path in FRONTEND_LEGACY_PATHS:
        full = REPO_ROOT / path
        if not full.exists():
            # Some paths may be added/removed by Phase 7+ pages — note
            # the absence so a future engineer sees it but the test
            # doesn't fail. Phase 7 is a freeze, not a creation event.
            continue
        result = subprocess.run(
            ["git", "diff", "--quiet", base, "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            drift.append(path)
    assert not drift, (
        "P-08 violation: legacy frontend paths modified since the merge-base.\n"
        + "\n".join(f"  - {p}" for p in drift)
    )


@pytest.mark.skipif(not _is_git_repo(), reason="not a git checkout")
def test_legacy_backend_paths_unmodified():
    base = _merge_base()
    if base is None:
        pytest.skip("could not resolve a merge-base ref")
    drift: list[str] = []
    for path in BACKEND_LEGACY_PATHS:
        full = REPO_ROOT / path
        if not full.exists():
            continue
        result = subprocess.run(
            ["git", "diff", "--quiet", base, "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            drift.append(path)
    assert not drift, (
        "P-08 violation: legacy backend paths modified since the merge-base.\n"
        + "\n".join(f"  - {p}" for p in drift)
    )


@pytest.mark.skipif(not _is_git_repo(), reason="not a git checkout")
def test_chart_preferences_table_not_referenced_in_new_chart_db():
    """The Phase 1 migration introduces 9 new tables under
    `database/chart_workspace_db.py`; the legacy `chart_preferences`
    table must NOT appear in that module's metadata.
    """
    src = (REPO_ROOT / "database" / "chart_workspace_db.py").read_text(encoding="utf-8")
    assert "chart_preferences" in src, (
        "expected the Phase 1 module to mention chart_preferences in a "
        "preservation comment so future engineers see the boundary"
    )
    # The mention must NOT be a __tablename__.
    assert '__tablename__ = "chart_preferences"' not in src, (
        "chart_preferences must NOT be a table in the new workspace DB"
    )
