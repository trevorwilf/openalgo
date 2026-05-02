"""Phase 2 T-10 — byte-identical relocation of the IST timezone object.

Five module-level ``IST = pytz.timezone("Asia/Kolkata")`` constants
existed across ``database/market_calendar_db.py``,
``blueprints/python_strategy.py``, ``utils/auth_utils.py``,
``sandbox/catch_up_processor.py``, and ``sandbox/squareoff_thread.py``.
Phase 2 T-10 makes ``market_regions/india/sessions.py`` the single
source of truth and has the five legacy paths re-export the symbol.

This test pins the relocation so future drift fails loudly.
"""

from __future__ import annotations

import pytz

from market_regions.india.sessions import IST


def test_ist_is_asia_kolkata():
    assert str(IST) == "Asia/Kolkata"


def test_ist_is_pytz_timezone_instance():
    # pytz caches timezone objects by name; the re-exported object
    # must be the same instance everywhere.
    assert IST is pytz.timezone("Asia/Kolkata")


def test_legacy_modules_reexport_same_object():
    """Each previously-inline IST constant must now be the same
    instance as the relocated one. Identity (``is``) is the strongest
    check — if any caller forks its own pytz.timezone() literal, this
    test fails immediately."""
    from blueprints.python_strategy import IST as bp_ist
    from database.market_calendar_db import IST as db_ist
    from sandbox.catch_up_processor import IST as catchup_ist
    from sandbox.squareoff_thread import IST as squareoff_ist
    from utils.auth_utils import IST as auth_ist

    for label, candidate in [
        ("blueprints.python_strategy.IST", bp_ist),
        ("database.market_calendar_db.IST", db_ist),
        ("sandbox.catch_up_processor.IST", catchup_ist),
        ("sandbox.squareoff_thread.IST", squareoff_ist),
        ("utils.auth_utils.IST", auth_ist),
    ]:
        assert candidate is IST, (
            f"{label} drifted from market_regions.india.sessions.IST; "
            "Phase 2 T-10 requires every legacy IST constant to be a "
            "re-export of the relocated source."
        )
