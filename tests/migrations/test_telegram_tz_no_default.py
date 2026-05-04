"""T-07 — telegram bot user_preferences DDL has no Asia/Kolkata default.

Phase 2 contract: the ``user_preferences`` table DDL no longer
declares ``DEFAULT 'Asia/Kolkata'`` for the ``timezone`` column.
New rows must supply the tz from the active broker's region
capability declaration via the dispatcher path
(``market_regions/india/legacy_v1/database/telegram_db.py``).
Existing rows are preserved by ``migrate_telegram_timezone_source.py``
backfill semantics.
"""

from __future__ import annotations

import re
from pathlib import Path

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "upgrade"
    / "migrate_telegram_bot.py"
)


def test_user_preferences_timezone_has_no_india_default() -> None:
    text = _MIGRATION.read_text(encoding="utf-8")
    # The DDL string for user_preferences should not contain a
    # DEFAULT clause for the timezone column. Prior pattern:
    # ``timezone VARCHAR(50) DEFAULT 'Asia/Kolkata'``.
    forbidden = re.compile(
        r"timezone\s+VARCHAR\([^)]+\)\s+DEFAULT\s+['\"]Asia/Kolkata['\"]",
        re.IGNORECASE,
    )
    assert not forbidden.search(text), (
        "migrate_telegram_bot.py declares ``DEFAULT 'Asia/Kolkata'`` "
        "on user_preferences.timezone. T-07 requires NOT NULL with "
        "no default; new rows must supply tz from the active broker's "
        "region capability declaration."
    )


def test_user_preferences_timezone_is_not_null() -> None:
    """The column is now NOT NULL — inserts without a tz value
    fail at the DB layer."""
    text = _MIGRATION.read_text(encoding="utf-8")
    # The user_preferences DDL block contains the timezone column
    # declaration. We assert the NOT NULL marker is present.
    pattern = re.compile(
        r"timezone\s+VARCHAR\([^)]+\)\s+NOT\s+NULL", re.IGNORECASE
    )
    assert pattern.search(text), (
        "migrate_telegram_bot.py user_preferences.timezone column "
        "must be declared NOT NULL post T-07."
    )
