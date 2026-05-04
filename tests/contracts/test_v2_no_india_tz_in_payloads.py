"""T-08 — v2 endpoint responses do not contain India-specific tz literals.

Phase 2 contract test (verify-only): the v2 ``accounts`` endpoint and
its peers must not embed ``+05:30`` (the IST UTC offset),
``Asia/Kolkata``, or ``IST`` in their response payloads when the
active broker is non-India. The ``+05:30`` strings that appear in
test capture data originate downstream (broker API responses for
India brokers); the v2 layer itself stays region-neutral.

The scan walks ``restx_api/v2/`` source files for the literals; any
hit is a regression that should route through
``utils.venue_local_time`` (post-T-01/T-02) instead of inlining the
India-specific values.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_V2_DIR = _REPO_ROOT / "restx_api" / "v2"

_INDIA_TZ_LITERALS = re.compile(
    r'"\+05:30"'
    r"|'\+05:30'"
    r'|"Asia/Kolkata"'
    r"|'Asia/Kolkata'"
    r'|"IST"'
    r"|'IST'"
)


def _v2_python_files() -> list[Path]:
    return [p for p in _V2_DIR.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize(
    "path",
    _v2_python_files(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)).replace("\\", "/"),
)
def test_v2_source_has_no_india_tz_literal(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    matches = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _INDIA_TZ_LITERALS.search(line):
            matches.append(
                f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}"
            )
    assert not matches, (
        f"{path.relative_to(_REPO_ROOT)} contains an India-specific tz "
        "literal in promoted v2 source. Use "
        "utils.venue_local_time.active_render_tz_name() (or per-venue "
        "venue_local_now/format_venue_local_time) so non-India brokers "
        "see their actual tz. Hits:\n  " + "\n  ".join(matches)
    )
