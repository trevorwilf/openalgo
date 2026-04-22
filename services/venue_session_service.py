"""VenueSessionService — timezone + session windows driven by venue records.

Phase 4 of the market-agnostic refactor. Answers questions like "is
NSE open at 2026-04-21T03:00:00Z?", "when is NYSE's next session after
now?", "what are the session windows for LSE on 2026-06-01?" without
any code branch on exchange string.

Uses ``zoneinfo`` (stdlib ≥ 3.9) rather than ``pytz`` — new code only.
pytz remains in legacy code paths until those migrate.

Behavioral model::

    1. Load venue.timezone_name.
    2. For a date, find schedule_templates rows for that day_of_week
       (including ``day_of_week == -1`` for 24/7 markets).
    3. Apply exceptions for that date in order:
         CLOSED           → drop every session window for the date
         EARLY_CLOSE      → truncate matching session to the earlier end
         LATE_OPEN        → delay matching session's start
         SPECIAL_SESSION  → add a new session window alongside the
                            default templates (e.g. Muhurat Trading,
                            holiday-evening MCX).
    4. Combine venue-local (start, end) times with the date and the
       venue timezone; convert both to UTC for the returned
       ``SessionWindow``.

The service is read-only. Writes to the new tables go through the repo
layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from database import venue_schedule_repo
from database.instruments_repo import venues_get
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionWindow:
    """A single open session window for a venue."""

    venue_code: str
    session_type: str
    start_utc: datetime
    end_utc: datetime
    venue_timezone_name: str


@dataclass(frozen=True)
class ActiveSession:
    """A session window the venue is currently inside of."""

    venue_code: str
    session_type: str
    start_utc: datetime
    end_utc: datetime


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VenueSessionService:
    """Stateless service (besides its repo handle). Safe to share."""

    def __init__(
        self,
        repo: Any = None,
        clock: Any = None,
    ) -> None:
        self._repo = repo or venue_schedule_repo
        self._clock = clock  # for tests; used only where explicit

    # ---- public API ---------------------------------------------------

    def venue_timezone(self, venue_code: str) -> ZoneInfo:
        venue = venues_get(venue_code)
        if venue is None:
            raise ValueError(f"no venue row for {venue_code!r}")
        return ZoneInfo(venue.timezone_name)

    def is_open(self, venue_code: str, at: datetime) -> bool:
        """True iff `at` falls within any active session window on that date."""
        sessions = self._windows_for_date(venue_code, at)
        at_utc = self._ensure_utc(at)
        for win in sessions:
            if win.start_utc <= at_utc < win.end_utc:
                return True
        return False

    def current_sessions(
        self, venue_code: str, at: datetime
    ) -> list[ActiveSession]:
        """Return every session window the venue is currently inside of."""
        at_utc = self._ensure_utc(at)
        out: list[ActiveSession] = []
        for win in self._windows_for_date(venue_code, at):
            if win.start_utc <= at_utc < win.end_utc:
                out.append(
                    ActiveSession(
                        venue_code=win.venue_code,
                        session_type=win.session_type,
                        start_utc=win.start_utc,
                        end_utc=win.end_utc,
                    )
                )
        return out

    def next_session(
        self, venue_code: str, after: datetime
    ) -> Optional[SessionWindow]:
        """Return the earliest session window that starts strictly after
        `after`, or None if nothing found in the next 14 venue-local days.
        """
        after_utc = self._ensure_utc(after)
        tz = self.venue_timezone(venue_code)
        local_start = after_utc.astimezone(tz).date()
        for offset in range(0, 15):
            day = local_start + timedelta(days=offset)
            windows = self._windows_for_date_local(venue_code, day, tz)
            for win in windows:
                if win.start_utc > after_utc:
                    return win
        return None

    def previous_close(
        self, venue_code: str, before: datetime
    ) -> Optional[datetime]:
        """Return the most recent session end time at or before ``before``.

        Scans up to 14 venue-local days back.
        """
        before_utc = self._ensure_utc(before)
        tz = self.venue_timezone(venue_code)
        local_end = before_utc.astimezone(tz).date()
        best: Optional[datetime] = None
        for offset in range(0, 15):
            day = local_end - timedelta(days=offset)
            windows = self._windows_for_date_local(venue_code, day, tz)
            for win in windows:
                if win.end_utc <= before_utc:
                    if best is None or win.end_utc > best:
                        best = win.end_utc
            if best is not None:
                return best
        return best

    def trading_days_in_range(
        self, venue_code: str, start: date, end: date
    ) -> list[date]:
        """Inclusive range of venue-local dates that have at least one
        active session (post-exception).
        """
        if end < start:
            return []
        tz = self.venue_timezone(venue_code)
        days: list[date] = []
        cur = start
        while cur <= end:
            if self._windows_for_date_local(venue_code, cur, tz):
                days.append(cur)
            cur += timedelta(days=1)
        return days

    def session_boundaries_for_date(
        self, venue_code: str, d: date
    ) -> list[SessionWindow]:
        """All session windows active on the given venue-local date
        (post-exception).
        """
        tz = self.venue_timezone(venue_code)
        return self._windows_for_date_local(venue_code, d, tz)

    # ---- internals ----------------------------------------------------

    def _windows_for_date(
        self, venue_code: str, ref_dt: datetime
    ) -> list[SessionWindow]:
        tz = self.venue_timezone(venue_code)
        local_date = self._ensure_utc(ref_dt).astimezone(tz).date()
        return self._windows_for_date_local(venue_code, local_date, tz)

    def _windows_for_date_local(
        self, venue_code: str, d: date, tz: ZoneInfo
    ) -> list[SessionWindow]:
        """Compute the post-exception session windows for (venue, date)."""
        tz_name = str(tz)
        templates = self._repo.templates_for_venue(
            venue_code, day_of_week=d.weekday()
        )
        exceptions = self._repo.exceptions_for_date(venue_code, d)

        # Bucket exceptions by type + session_type.
        closed_session_types: set[str] = set()
        closed_all = False
        early_close: dict[str, time] = {}
        late_open: dict[str, time] = {}
        special_sessions: list[tuple[str, time, time]] = []

        for ex in exceptions:
            if ex.exception_type == "CLOSED":
                if ex.session_type is None:
                    closed_all = True
                else:
                    closed_session_types.add(ex.session_type)
            elif ex.exception_type == "EARLY_CLOSE" and ex.session_type and ex.ends_at_local:
                early_close[ex.session_type] = ex.ends_at_local
            elif ex.exception_type == "LATE_OPEN" and ex.session_type and ex.starts_at_local:
                late_open[ex.session_type] = ex.starts_at_local
            elif (
                ex.exception_type == "SPECIAL_SESSION"
                and ex.session_type
                and ex.starts_at_local
                and ex.ends_at_local
            ):
                special_sessions.append(
                    (ex.session_type, ex.starts_at_local, ex.ends_at_local)
                )

        windows: list[SessionWindow] = []

        if not closed_all:
            for t in templates:
                if t.session_type in closed_session_types:
                    continue
                start_local = late_open.get(t.session_type, t.starts_at_local)
                end_local = early_close.get(t.session_type, t.ends_at_local)
                # EARLY_CLOSE applied after LATE_OPEN; clamp defensively.
                if end_local <= start_local:
                    continue
                windows.append(
                    self._make_window(
                        venue_code, t.session_type,
                        d, start_local, end_local, tz, tz_name,
                    )
                )

        # Special sessions get added on top (e.g. Muhurat Trading).
        for session_type, start, end in special_sessions:
            windows.append(
                self._make_window(
                    venue_code, session_type, d, start, end, tz, tz_name
                )
            )

        windows.sort(key=lambda w: w.start_utc)
        return windows

    @staticmethod
    def _make_window(
        venue_code: str,
        session_type: str,
        d: date,
        start_local: time,
        end_local: time,
        tz: ZoneInfo,
        tz_name: str,
    ) -> SessionWindow:
        start_local_dt = datetime.combine(d, start_local, tzinfo=tz)
        end_local_dt = datetime.combine(d, end_local, tzinfo=tz)
        return SessionWindow(
            venue_code=venue_code,
            session_type=session_type,
            start_utc=start_local_dt.astimezone(timezone.utc),
            end_utc=end_local_dt.astimezone(timezone.utc),
            venue_timezone_name=tz_name,
        )

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            raise ValueError(
                "VenueSessionService requires tz-aware datetimes (pass UTC)"
            )
        return dt.astimezone(timezone.utc)


def venue_tz_or_default(
    venue_code: str | None, default: str = "Asia/Kolkata"
) -> str:
    """Return the venue's IANA timezone name, or a default.

    Gated by ``VENUE_SESSION_V2``. When the flag is off the default is
    always returned — this is the migration seam legacy services use
    to keep byte-identical Indian behavior until the canary flips.

    On a cache miss or any error the default is also returned. Never
    raises.

    Returns a *string* (e.g. ``"Asia/Kolkata"``, ``"America/New_York"``)
    rather than a ``ZoneInfo`` so legacy callers that wrap the result
    in ``pytz.timezone(...)`` keep working unchanged.
    """
    from utils.feature_flags import is_enabled

    if not is_enabled("VENUE_SESSION_V2"):
        return default
    if not venue_code:
        return default
    try:
        venue = venues_get(venue_code)
    except Exception:
        return default
    if venue is None or not venue.timezone_name:
        return default
    return venue.timezone_name


__all__ = [
    "ActiveSession",
    "SessionWindow",
    "VenueSessionService",
    "venue_tz_or_default",
]
