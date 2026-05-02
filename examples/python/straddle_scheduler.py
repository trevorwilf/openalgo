# Phase 8 (T-28) / C-P2-027 — region-aware example.
#
# *This example uses India-specific values* (NIFTY index option,
# NSE_INDEX venue, NRML product, IST schedule).  Pass ``--region us``
# (or any non-India region) once a US options chain provider ships;
# until then this script exits early on non-India regions.

import argparse
import time

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from openalgo import api


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="India NIFTY straddle scheduler example")
    p.add_argument("--region", default="india")
    p.add_argument("--venue-tz", default="Asia/Kolkata")
    return p.parse_args()


_ARGS = _parse_args() if __name__ == "__main__" else argparse.Namespace(region="india", venue_tz="Asia/Kolkata")
if str(_ARGS.region).lower() != "india":
    raise SystemExit(
        f"This example covers India-only flows; got --region={_ARGS.region!r}. "
        "See docs/refactor/future-broker-onboarding-checklist.md for the "
        "US/EU/UK roadmap."
    )

print("🔁 OpenAlgo Python Bot is running.")

# ===============================
# OpenAlgo Client
# ===============================
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000",
)

NIFTY_LOT = 75  # NSE Index lot size
LOTS = 1  # Number of lots


# ===============================
# Function to Place Straddle
# ===============================
def place_nifty_straddle_0920():
    try:
        # Fetch NIFTY INDEX Quote (must print immediately)
        quote = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
        print("NIFTY QUOTE:", quote)

        qty = LOTS * NIFTY_LOT

        # Place optionsmultiorder short straddle
        response = client.optionsmultiorder(
            strategy="NIFTY_09DEC25_STRADDLE_0920",
            underlying="NIFTY",
            exchange="NSE_INDEX",
            expiry_date="09DEC25",  # FIXED EXPIRY
            legs=[
                {
                    "offset": "ATM",
                    "option_type": "CE",
                    "action": "SELL",
                    "quantity": qty,
                    "product": "NRML",
                },
                {
                    "offset": "ATM",
                    "option_type": "PE",
                    "action": "SELL",
                    "quantity": qty,
                    "product": "NRML",
                },
            ],
        )

        print("ORDER RESPONSE:", response)

    except Exception as e:
        print("Error:", e)


# ===============================
# Schedule the Job at 09:20 IST
# ===============================
def schedule_straddle():
    # Phase 8 (T-28) — venue tz from ``--venue-tz``; default
    # Asia/Kolkata for backward compatibility.
    venue_tz = pytz.timezone(_ARGS.venue_tz)
    scheduler = BackgroundScheduler(timezone=venue_tz)

    scheduler.add_job(
        place_nifty_straddle_0920,
        trigger="cron",
        day_of_week="mon-sun",
        hour=9,
        minute=20,
        id="nifty_0920_straddle",
    )

    scheduler.start()
    print("✅ Scheduled NIFTY 09DEC25 ATM Straddle for 09:20 IST (Mon–Sun).")

    return scheduler


if __name__ == "__main__":
    scheduler = schedule_straddle()

    # Keep script alive
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
