# Inventory 08 — `(symbol, exchange)` composite keys in historify

## Summary

`database/historify_db.py` stores OHLCV and watchlist data under the
composite primary key `(symbol, exchange, interval, timestamp)` — and
the watchlist under `(symbol, exchange)`. Data catalog and job records
carry the same pair. No broker provenance, no `instrument_id`, so two
brokers' identical `(RELIANCE, NSE)` collide (in practice they don't,
because the legacy single-broker model prevents it — but the schema
does not enforce provenance).

Phase 3b adds `instrument_id` as an additive column. Phase 3b does NOT
drop the composite keys; it adds `instrument_id` and indexes on it,
keeping v1 writes working.

## Raw citations

```
# Schema with composite keys
database/historify_db.py:116     PRIMARY KEY (symbol, exchange, interval, timestamp)
database/historify_db.py:128     UNIQUE (symbol, exchange)                        (watchlist)
database/historify_db.py:143     UNIQUE (symbol, exchange, interval)              (data_catalog)
database/historify_db.py:194     PRIMARY KEY (symbol, exchange)                   (data_ranges)

# Key lookups and joins across historify
database/historify_db.py:285,322,353,379,383,384,391,450,467,477,480
database/historify_db.py:564-567,624,1148-1181,1320,1330,1408-1414
database/historify_db.py:1644,1740,1827,1830,1955,1966,2162,2191,2359,2375,2389,2463-2469,2550,2830-2836

# Service layer uses the same keys
services/historify_service.py:49       def validate_symbol(symbol, exchange)
services/historify_service.py:100,114,128,132,144,156,159    add/remove watchlist
services/historify_service.py:178,219,233,238,245,250,252,286,318,355,357
services/historify_service.py:452,544,559,597,692,710,784,798,815,901,916,944,968,983,1011,1363,1540,2055

# Scheduler picks jobs keyed the same way
services/historify_scheduler_service.py   (same (symbol, exchange) pairing)
```

## Blast radius

- **Phase 2a (additive schema)** — creates `instruments` table; not
  used by historify yet.
- **Phase 3b (historify `instrument_id` migration)** — adds
  `instrument_id` column to `market_data`, `watchlist`, `data_catalog`,
  `data_ranges`, and `job_items` (all additive), plus a composite
  index on `(instrument_id, interval, timestamp)`. Legacy columns and
  composite PKs stay. Writes additively populate both old and new
  columns. Reads remain legacy until flagged.
- **Phase 6 (`/api/v2`)** — v2 historify endpoints take/return
  `instrument_id`. v1 endpoints untouched.

Invariant: historify keeps `(symbol, exchange)` as primary keys through
Phase 9. Additive only.
