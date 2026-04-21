# Inventory 09 — Chart-path timezone coercion (IST hard-dependency)

## Summary

The three chart services (`services/iv_chart_service.py`,
`services/straddle_chart_service.py`, `services/custom_straddle_service.py`)
take naive broker-returned timestamps and `tz_localize("UTC")` →
`tz_convert("Asia/Kolkata")`, then render everything assuming IST. The
returned DataFrames have a datetime index in IST, and downstream
code (strategy math, chart renderers) reads the index without ever
re-checking tz. A US-venue chart flowing through these services today
would visually shift by 5.5 hours.

Phase 4 (venue/session/timezone normalization) resolves the timezone
from the venue record, not a literal.

## Raw citations

```
# services/iv_chart_service.py
60-61:    candle_time: datetime of the candle (naive, treated as IST)
60-61:    expiry: datetime of option expiry (naive, IST)
97-98:    Convert timestamp column in a history DataFrame to IST datetime index.
100:      ist = pytz.timezone("Asia/Kolkata")
110-122:  df["datetime"] = df["datetime"].dt.tz_convert(ist)  # already-aware path
           df["datetime"] = df["datetime"].dt.tz_localize("UTC").dt.tz_convert(ist)  # naive path
167:      ist = pytz.timezone("Asia/Kolkata")
286:      # Convert timestamps to IST
365-368:  df_option / df_underlying docstring: "datetime index in IST"

# services/straddle_chart_service.py
63-64:    Convert timestamp column in a history DataFrame to IST datetime index.
66:       ist = pytz.timezone("Asia/Kolkata")
76-88:    dt.tz_convert(ist) / dt.tz_localize("UTC").dt.tz_convert(ist) pair
125,346:  ist = pytz.timezone("Asia/Kolkata")
349:      # Set expiry to 15:30 IST (market close)

# services/custom_straddle_service.py
60:       ist = pytz.timezone("Asia/Kolkata")

# services/market_calendar_service.py
46:       {"status": "success", "year": year, "timezone": "Asia/Kolkata", "data": holidays}
          (v1 output literally labels "Asia/Kolkata" — frozen under ADR 0003 for v1)
```

## Blast radius

- **Phase 1a (domain)** — `NormalizedBar.period_start` is tz-aware UTC.
  `venue_timezone` optional for rendering.
- **Phase 4 (venue/session/timezone normalization)** — chart services
  resolve tz via `instrument.venue_code → venue.timezone_name` when
  converting for display. v1 chart responses keep emitting IST-formatted
  timestamps because ADR 0003 freezes v1 shape (incl. the
  `"timezone": "Asia/Kolkata"` label in
  `services/market_calendar_service.py:46`).
- **Phase 6 (`/api/v2`)** — v2 chart endpoints emit UTC + a venue_tz
  hint. Clients localize.
- **Phase 9 (flags/canary)** — RESOLVER_V2 + CHART_VENUE_TZ_V2 flags
  co-gate the chart services.

Invariant: v1 chart responses remain IST-labelled. New chart code
resolves tz from the venue record, not a string literal.
