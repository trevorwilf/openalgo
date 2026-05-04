"""T-25 (v7 Phase 5-partial) — frontend region siblings exist.

Asserts that ``frontend/src/{us,eu,uk}/`` directories exist with at
least an ``index.ts`` entry barrel. The full sibling structure
(pages/components/api/hooks/lib mirroring ``india_legacy/``)
expands per-component as Phase 5 follow-ups land. This contract
test pins the minimum-viable scaffold so the directories don't
accidentally disappear.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("region", ["us", "eu", "uk"])
def test_region_sibling_dir_exists(region: str) -> None:
    region_dir = _REPO_ROOT / "frontend" / "src" / region
    assert region_dir.is_dir(), f"frontend/src/{region}/ missing"
    assert (region_dir / "index.ts").is_file(), f"frontend/src/{region}/index.ts missing"
    assert (region_dir / "README.md").is_file(), f"frontend/src/{region}/README.md missing"


@pytest.mark.parametrize("region", ["us", "eu", "uk"])
def test_region_sibling_declares_region_code(region: str) -> None:
    """The index.ts entry barrel exports a REGION_CODE constant the
    router uses for sibling selection."""
    barrel = _REPO_ROOT / "frontend" / "src" / region / "index.ts"
    text = barrel.read_text(encoding="utf-8")
    assert f"REGION_CODE = '{region}'" in text


def test_india_legacy_sibling_unchanged():
    """Sanity: india_legacy/ remains the production India UI. T-25
    is purely additive — nothing in india_legacy/ moves."""
    india_legacy = _REPO_ROOT / "frontend" / "src" / "india_legacy"
    assert india_legacy.is_dir()
    for sub in ("pages", "components", "api", "hooks", "lib"):
        assert (india_legacy / sub).is_dir(), (
            f"india_legacy/{sub}/ disappeared — T-25 must be additive"
        )
