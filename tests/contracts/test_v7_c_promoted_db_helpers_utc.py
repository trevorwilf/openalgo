"""v7-C precursor — promoted DB helpers stamp UTC.

Phase 1 (T-03) migrated 4 PROMOTED_CORE database helpers to stamp
``datetime.now(timezone.utc)`` at write time. The full v7-C
invariant ships with T-33 (Phase 4); this precursor locks the
Phase 1 deliverable.

The scan is intentionally regex-based — we want a future
regression where someone re-introduces an IST-anchored stamp to
fail before the parity baselines run, not silently after.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROMOTED_DB_HELPERS = (
    "database/auth_db.py",
    "database/action_center_db.py",
    "database/analyzer_db.py",
    "database/apilog_db.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Either a direct datetime.now(timezone.utc), datetime.now(pytz.utc),
# datetime.now(pytz.UTC), or datetime.utcnow() is acceptable. The
# function name varies (``_now_utc``, ``get_utc_timestamp``, etc.)
# so we just assert at least one of these patterns appears.
_UTC_STAMP_PATTERNS = (
    re.compile(r"datetime\.now\(\s*timezone\.utc\s*\)"),
    re.compile(r"datetime\.now\(\s*pytz\.utc\s*\)"),
    re.compile(r"datetime\.now\(\s*pytz\.UTC\s*\)"),
)

# Note on scope: the negative assertion (no IST literal in the file
# at all) belongs to T-33 / v7-C full invariant in Phase 4. Phase 1
# only commits to the positive assertion below — that the UTC stamp
# pattern is present. Lines that legitimately read
# SESSION_EXPIRY_TIMEZONE (with an IST default) are T-10's
# concern in Phase 2.


@pytest.mark.parametrize("relpath", _PROMOTED_DB_HELPERS)
def test_promoted_db_helper_stamps_utc(relpath: str) -> None:
    path = _REPO_ROOT / relpath
    text = path.read_text(encoding="utf-8")
    has_utc = any(p.search(text) for p in _UTC_STAMP_PATTERNS)
    assert has_utc, (
        f"Promoted DB helper {relpath} no longer contains a UTC "
        "stamp pattern. T-03 expects datetime.now(timezone.utc) (or "
        "the pytz.utc equivalent) at the persistence layer."
    )
