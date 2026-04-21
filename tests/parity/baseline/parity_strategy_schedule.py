"""Parity harness: strategy schedule next-run computation.

Uses APScheduler's CronTrigger with an IST timezone to compute the next
fire time from a fixed "now". This mirrors the scheduling logic in
`blueprints/python_strategy.py:1415`. Phase 4 replaces the hard IST
dependency with a venue-timezone lookup; the fixture lets us assert the
legacy Indian behavior survives.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.parity import _common  # noqa: E402,F401

import pytz
from apscheduler.triggers.cron import CronTrigger

NAME = "parity_strategy_schedule"

IST = pytz.timezone("Asia/Kolkata")

# Fixed "now" so the fixture is deterministic. Monday 2026-04-20 07:00 IST.
FIXED_NOW_IST = IST.localize(datetime(2026, 4, 20, 7, 0, 0))

SCHEDULES = [
    {"label": "nse_open_weekdays", "hour": 9, "minute": 15,
     "day_of_week": "mon,tue,wed,thu,fri"},
    {"label": "nse_close_weekdays", "hour": 15, "minute": 30,
     "day_of_week": "mon,tue,wed,thu,fri"},
    {"label": "mcx_evening_open", "hour": 17, "minute": 0,
     "day_of_week": "mon,tue,wed,thu,fri"},
    {"label": "mcx_close", "hour": 23, "minute": 55,
     "day_of_week": "mon,tue,wed,thu,fri"},
    {"label": "crypto_midnight_daily", "hour": 0, "minute": 0,
     "day_of_week": "mon,tue,wed,thu,fri,sat,sun"},
]


def generate() -> Dict[str, Any]:
    results = []
    for s in SCHEDULES:
        trig = CronTrigger(
            hour=s["hour"],
            minute=s["minute"],
            day_of_week=s["day_of_week"],
            timezone=IST,
        )
        next_fire = trig.get_next_fire_time(None, FIXED_NOW_IST)
        results.append({
            "label": s["label"],
            "schedule": {k: s[k] for k in ("hour", "minute", "day_of_week")},
            "next_fire_iso": next_fire.isoformat() if next_fire else None,
            "next_fire_weekday": next_fire.strftime("%A") if next_fire else None,
        })
    return {
        "harness": NAME,
        "fixed_now_ist": FIXED_NOW_IST.isoformat(),
        "schedules": results,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(generate(), indent=2, sort_keys=True))
