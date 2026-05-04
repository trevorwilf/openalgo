import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import pytz
from dotenv import load_dotenv
from openalgo import api
from sqlalchemy import MetaData, create_engine

# Load environment variables
load_dotenv()

API_KEY = os.getenv("API_KEY")
DB_NAME = os.getenv("DB_NAME", "amibroker.db")
INTERVAL = os.getenv("INTERVAL", "1m")
HOST = os.getenv("HOST", "http://127.0.0.1:5000")
MAX_RPS = int(os.getenv("MAX_REQUESTS_PER_SECOND", 10))
POLL_INTERVAL = int(os.getenv("POLLING_INTERVAL_SECONDS", 5))
INITIAL_DAYS = int(os.getenv("INITIAL_DAYS", 30))

# T-11 (Phase 2): venue tz fail-closed for non-India deployments.
# Resolution chain:
#   * DOWNLOAD_VENUE_TZ env set + valid IANA   -> use it
#   * DOWNLOAD_VENUE_TZ env set + invalid IANA -> ConfigurationError
#   * env unset + active region resolves       -> resolve venue tz
#                                                  from the region's
#                                                  default_venue_codes[0]
#                                                  via _venue_iana_tz
#   * env unset + region unresolvable          -> Asia/Kolkata
#                                                  (legacy India
#                                                  script behavior)
def _resolve_download_venue_tz() -> "pytz.BaseTzInfo":
    raw = os.getenv("DOWNLOAD_VENUE_TZ")
    if raw:
        try:
            return pytz.timezone(raw)
        except pytz.UnknownTimeZoneError:
            from domain.errors import ConfigurationError

            raise ConfigurationError(
                f"DOWNLOAD_VENUE_TZ={raw!r} is not a valid IANA "
                f"timezone name. Set it to your venue's IANA tz "
                f"(e.g., Asia/Kolkata for India, America/New_York "
                f"for US, Europe/London for UK).",
                missing_env="DOWNLOAD_VENUE_TZ",
            )

    # env unset — try to resolve from the active region's primary
    # venue. Failing that, fall back to Asia/Kolkata (legacy
    # India-script behavior; the script is historically India-only).
    try:
        from utils.venue_local_time import active_render_tz_name

        return pytz.timezone(active_render_tz_name())
    except Exception:
        return pytz.timezone("Asia/Kolkata")


_VENUE_TZ = _resolve_download_venue_tz()

# Paths
DB_FOLDER = os.path.join("..", "db")
os.makedirs(DB_FOLDER, exist_ok=True)

DB_PATH = os.path.join(DB_FOLDER, DB_NAME)
CHECKPOINT_FILE = os.path.join(DB_FOLDER, "checkpoints.json")

# Setup
client = api(api_key=API_KEY, host=HOST)
engine = create_engine(f"sqlite:///{DB_PATH}")
metadata = MetaData()
metadata.reflect(bind=engine)

# Load checkpoints
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE) as f:
        checkpoints = json.load(f)
else:
    checkpoints = {}


def save_checkpoints():
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoints, f, indent=2)


def get_symbols():
    if not os.path.exists("symbols.csv"):
        return []
    df = pd.read_csv("symbols.csv", header=None)
    return df[0].dropna().astype(str).str.strip().tolist()


def fetch_and_store(symbol):
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = checkpoints.get(
        symbol, (datetime.now() - pd.Timedelta(days=INITIAL_DAYS)).strftime("%Y-%m-%d")
    )
    end_date = today

    response = client.history(
        symbol=symbol, exchange="NSE", interval=INTERVAL, start_date=start_date, end_date=end_date
    )

    if not isinstance(response, pd.DataFrame) or response.empty:
        print(f"[{symbol}] No data returned or invalid response.")
        return

    df = response
    df.index = pd.to_datetime(df.index)
    df = df[df.index.strftime("%Y-%m-%d") >= start_date]

    if df.empty:
        print(f"[{symbol}] No new rows after filtering.")
        return

    # Phase 8 (T-27) — convert timestamps from UTC to the venue's
    # local time. Replaces the legacy hardcoded "subtract 5:30
    # hours". The venue tz comes from DOWNLOAD_VENUE_TZ (default
    # Asia/Kolkata for India backward compatibility). pandas
    # tz_localize+tz_convert handles DST correctly for US/EU venues.
    if df.index.tz is None:
        utc_index = df.index.tz_localize("UTC")
    else:
        utc_index = df.index.tz_convert("UTC")
    venue_local = utc_index.tz_convert(_VENUE_TZ).tz_localize(None)

    df["SYMBOL"] = symbol
    df["DATE"] = venue_local.strftime("%Y-%m-%d %H:%M:%S")
    df = df[["SYMBOL", "DATE", "open", "high", "low", "close", "volume"]]
    df.columns = ["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]

    df.to_sql("stock_data", con=engine, if_exists="append", index=False)

    last_dt = df.index.max().strftime("%Y-%m-%d")
    checkpoints[symbol] = last_dt
    print(f"[{symbol}] Inserted {len(df)} records. Updated checkpoint: {last_dt}")


# Main loop with throttling
while True:
    try:
        symbols = get_symbols()
        for i, symbol in enumerate(symbols):
            fetch_and_store(symbol)
            if (i + 1) % MAX_RPS == 0:
                print("Rate limit reached. Sleeping 1s...")
                time.sleep(1)
        save_checkpoints()
        time.sleep(POLL_INTERVAL)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(POLL_INTERVAL)
