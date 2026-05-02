# Phase 8 (T-28) / C-P2-027 — region-aware example.
#
# *This example uses India-specific values* (NIFTY index option,
# NSE_INDEX venue, NFO derivatives venue, NRML product, IST schedule).
# Pass ``--region us`` (or any non-India region) once a corresponding
# US options chain provider ships — that's broker-plugin work
# documented in
# ``docs/refactor/future-broker-onboarding-checklist.md``.
#
# The ``--region`` argument is here today as a forward-compat scaffold.
# When a non-India region is selected, the script prints an explicit
# unsupported message and exits — the underlying ``client.optionchain``
# / ``client.placeoptionsorder`` calls assume India option grammar.

import argparse
import time

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from openalgo import api


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="India NIFTY straddle scheduler example")
    p.add_argument(
        "--region",
        default="india",
        help=(
            "Region code; defaults to 'india' for backward compatibility. "
            "Non-India regions exit with an unsupported notice today — "
            "future engagements add US/EU/UK options-chain providers."
        ),
    )
    p.add_argument(
        "--venue-tz",
        default="Asia/Kolkata",
        help="IANA timezone for the scheduler (default Asia/Kolkata).",
    )
    return p.parse_args()


_ARGS = _parse_args() if __name__ == "__main__" else argparse.Namespace(region="india", venue_tz="Asia/Kolkata")
if str(_ARGS.region).lower() != "india":
    raise SystemExit(
        f"This example covers India-only flows; got --region={_ARGS.region!r}. "
        "See docs/refactor/future-broker-onboarding-checklist.md for the "
        "US/EU/UK roadmap."
    )

print("🔁 OpenAlgo Python Bot is running.")

# =====================================
# OpenAlgo Client
# =====================================
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000",
)

NIFTY_LOT = 75
LOTS = 1


# =====================================
# STOPLOSS USING placeorder
# =====================================
def place_stoploss_order(symbol, sl_trigger, quantity):
    sl_price = round(sl_trigger + 2, 2)  # Trigger + 2 buffer for SL-LIMIT

    print(f"🔻 Sending SL Order → {symbol}")
    print(f"Trigger: {sl_trigger} | Price: {sl_price}")

    response = client.placeorder(
        strategy="NIFTY_09DEC25_STOPLOSS",
        symbol=symbol,
        action="BUY",  # BUY to exit short position
        exchange="NFO",
        price_type="SL",  # STOPLOSS-LIMIT order
        product="NRML",
        quantity=str(quantity),
        price=str(sl_price),
        trigger_price=str(sl_trigger),
        disclosed_quantity="0",
    )

    print("SL ORDER RESPONSE:", response)
    return response


# =====================================
# MAIN STRATEGY: ENTRY + STOPLOSS
# =====================================
def place_nifty_straddle_with_sl():
    print("\n🔥 Scheduled Trigger — Placing NIFTY Straddle...")

    # STEP 1 — Fetch NIFTY quote
    quote = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
    print("NIFTY QUOTE:", quote)

    qty = LOTS * NIFTY_LOT

    # STEP 2 — ENTRY using optionsmultiorder
    entry = client.optionsmultiorder(
        strategy="NIFTY_09DEC25_STRADDLE",
        underlying="NIFTY",
        exchange="NSE_INDEX",
        legs=[
            {
                "offset": "ATM",
                "option_type": "CE",
                "action": "SELL",
                "quantity": qty,
                "expiry_date": "09DEC25",
                "product": "NRML",
                "pricetype": "MARKET",
                "splitsize": 0,
            },
            {
                "offset": "ATM",
                "option_type": "PE",
                "action": "SELL",
                "quantity": qty,
                "expiry_date": "09DEC25",
                "product": "NRML",
                "pricetype": "MARKET",
                "splitsize": 0,
            },
        ],
    )

    print("ENTRY ORDER RESPONSE:", entry)

    ce_leg = entry["results"][0]
    pe_leg = entry["results"][1]

    ce_orderid = ce_leg["orderid"]
    pe_orderid = pe_leg["orderid"]

    ce_symbol = ce_leg["symbol"]
    pe_symbol = pe_leg["symbol"]

    # STEP 3 — Wait for execution
    time.sleep(5)

    # STEP 4 — Fetch average filled prices
    ce_status = client.orderstatus(order_id=ce_orderid, strategy="NIFTY_09DEC25_STRADDLE")
    pe_status = client.orderstatus(order_id=pe_orderid, strategy="NIFTY_09DEC25_STRADDLE")

    print("CE ORDERSTATUS:", ce_status)
    print("PE ORDERSTATUS:", pe_status)

    ce_entry = float(ce_status["data"]["average_price"])
    pe_entry = float(pe_status["data"]["average_price"])

    # STEP 5 — Calculate 30% Stoploss
    ce_sl_trigger = round(ce_entry * 1.30, 2)
    pe_sl_trigger = round(pe_entry * 1.30, 2)

    print(f"CE SL Trigger = {ce_sl_trigger}")
    print(f"PE SL Trigger = {pe_sl_trigger}")

    # STEP 6 — Place SL Orders using only placeorder
    place_stoploss_order(symbol=ce_symbol, sl_trigger=ce_sl_trigger, quantity=qty)

    place_stoploss_order(symbol=pe_symbol, sl_trigger=pe_sl_trigger, quantity=qty)

    print("\n🎯 All Stoploss Orders Placed Successfully.")


# =====================================
# SCHEDULER — 09:20 AM IST
# =====================================
def schedule_straddle():
    # Phase 8 (T-28) — venue tz comes from ``--venue-tz``; default
    # Asia/Kolkata for backward compatibility with the legacy India
    # default.
    venue_tz = pytz.timezone(_ARGS.venue_tz)
    scheduler = BackgroundScheduler(timezone=venue_tz)

    scheduler.add_job(
        place_nifty_straddle_with_sl,
        trigger="cron",
        day_of_week="mon-sun",
        hour=20,
        minute=49,
        id="nifty_straddle_0920",
    )

    scheduler.start()
    print("✅ Scheduled NIFTY 09DEC25 Straddle + SL at 20:49 AM IST (Mon–Sun)")
    return scheduler


if __name__ == "__main__":
    scheduler = schedule_straddle()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
