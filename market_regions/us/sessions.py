"""US session windows + timezone — Phase 7b T-30 build-out.

The America/New_York timezone object is the single source of truth
for the rest of the codebase to import as the US tz. Session windows
mirror NYSE / NASDAQ standard hours; specific brokers may narrow
these via their plugin's session-template overrides.
"""

from __future__ import annotations

from typing import Any

import pytz


# Single source of truth for the US tz. ``pytz.timezone`` caches by
# name so this is the same instance regardless of import path.
US_EASTERN: pytz.BaseTzInfo = pytz.timezone("America/New_York")


# Session windows in venue-local time (America/New_York). Days of
# week follow the v2 schema: 0=Mon ... 4=Fri. Pre-market and
# post-market are extended sessions; REGULAR is the official trading
# window.
SESSION_TEMPLATES: list[dict[str, Any]] = [
    {
        "session_code": "PRE_MARKET",
        "venue_codes": ["XNYS", "XNAS", "ARCX", "BATS"],
        "local_start_time": "04:00",
        "local_end_time": "09:30",
        "days_of_week": [0, 1, 2, 3, 4],
        "label": "US equity pre-market",
    },
    {
        "session_code": "REGULAR",
        "venue_codes": ["XNYS", "XNAS", "ARCX", "BATS"],
        "local_start_time": "09:30",
        "local_end_time": "16:00",
        "days_of_week": [0, 1, 2, 3, 4],
        "label": "US equity regular hours",
    },
    {
        "session_code": "POST_MARKET",
        "venue_codes": ["XNYS", "XNAS", "ARCX", "BATS"],
        "local_start_time": "16:00",
        "local_end_time": "20:00",
        "days_of_week": [0, 1, 2, 3, 4],
        "label": "US equity post-market",
    },
]


__all__ = ["SESSION_TEMPLATES", "US_EASTERN"]
