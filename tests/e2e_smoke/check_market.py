import os
from dotenv import load_dotenv
load_dotenv()
import httpx

KEY = (os.environ.get("BROKER_API_KEY") or "").strip(" '\"")
SEC = (os.environ.get("BROKER_API_SECRET") or "").strip(" '\"")
r = httpx.get(
    "https://paper-api.alpaca.markets/v2/clock",
    headers={"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC},
    timeout=10.0,
)
print(r.status_code, r.json())
