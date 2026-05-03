"""v7-B precursor — no IST literal in promoted blueprints.

Phase 1 (T-01, T-02) migrated 6 promoted blueprints from
``pytz.timezone("Asia/Kolkata")`` literals to
:func:`utils.venue_local_time.active_render_tz_name`. The full v7-B
invariant ships with T-33 (Phase 4); this precursor locks the
Phase 1 deliverable so a future regression that re-introduces the
literal fails CI immediately.

The scan is regex-based and matches both ``"Asia/Kolkata"`` and
``"IST"`` as standalone string literals. The blueprints listed
below are the 6 PROMOTED_CORE blueprints that surface timestamps to
the operator UI; they MUST NOT carry an IST literal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROMOTED_BLUEPRINTS = (
    "blueprints/pnltracker.py",
    "blueprints/analyzer.py",
    "blueprints/health.py",
    "blueprints/latency.py",
    "blueprints/log.py",
    "blueprints/traffic.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_IST_LITERAL = re.compile(r'"Asia/Kolkata"|\'Asia/Kolkata\'|"IST"|\'IST\'')


@pytest.mark.parametrize("relpath", _PROMOTED_BLUEPRINTS)
def test_promoted_blueprint_has_no_ist_literal(relpath: str) -> None:
    path = _REPO_ROOT / relpath
    text = path.read_text(encoding="utf-8")
    matches = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IST_LITERAL.search(line):
            matches.append(f"{relpath}:{lineno}: {line.strip()}")
    assert not matches, (
        f"Promoted blueprint {relpath} contains IST literal(s) — "
        "use utils.venue_local_time.active_render_tz_name() instead. "
        f"Hits:\n  " + "\n  ".join(matches)
    )
