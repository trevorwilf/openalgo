# Inventory 03 — `Asia/Kolkata` / `IST` literal references

## Summary

IST as a default timezone is baked into ~400 call sites across services,
blueprints, database helpers, broker data adapters, and the sandbox. The
market calendar (`database/market_calendar_db.py:28`) and the python
strategy scheduler (`blueprints/python_strategy.py:57`) each define their
own module-level `IST = pytz.timezone("Asia/Kolkata")`. Broker adapters
(aliceblue, compositedge, wisdom, jainamxts, ibulls, fivepaisaxts,
rmoney, groww, firstock, flattrade, definedge, fivepaisa, tradejini) all
call `pd.to_datetime(...).tz_localize("Asia/Kolkata")` inline on the
history path.

This inventory is the input to **Phase 4 (venue/session/timezone
normalization)**: venues carry their own IANA tz and no service reads
`"Asia/Kolkata"` as a literal.

## Raw citations

See the grep dump at
`tool-results/toolu_012FEtpytDaZViRf3njocP4U.txt` (400+ hits, ~70 files).
Representative clusters:

```
# Canonical IST constant definitions (module-level)
database/market_calendar_db.py:28    IST = pytz.timezone("Asia/Kolkata")
blueprints/python_strategy.py:57     IST = pytz.timezone("Asia/Kolkata")
utils/auth_utils.py:31               IST = pytz.timezone("Asia/Kolkata")
sandbox/catch_up_processor.py:22     IST = pytz.timezone("Asia/Kolkata")
test/test_python_strategy_exchange_aware.py:27   IST = pytz.timezone("Asia/Kolkata")
test/test_python_strategy_edge_cases.py:26       IST = pytz.timezone("Asia/Kolkata")

# Inline literals in services/blueprints (use datetime.now / tz_convert / tz_localize)
blueprints/analyzer.py:84,102
blueprints/chartink.py:58,236,833
blueprints/health.py:38
blueprints/latency.py:26
blueprints/log.py:82
blueprints/pnltracker.py:35,137,237,352,514,649,910,960,982
blueprints/sandbox.py:365,379,634
blueprints/strategy.py:60,286,883
blueprints/traffic.py:24
database/action_center_db.py:38
database/analyzer_db.py:100
database/apilog_db.py:80
database/auth_db.py:86,234
database/telegram_db.py:183,637   (stored tz='Asia/Kolkata' default)
restx_api/ticker.py:59
services/custom_straddle_service.py:60
services/iv_chart_service.py:100,167,286,365-368
services/straddle_chart_service.py:66,125,346,349
services/market_calendar_service.py:46
utils/session.py:32,52,74
utils.py:13

# Sandbox execution (multiple IST .now() calls)
sandbox/execution_engine.py:228,325,335,352,397,638
sandbox/order_manager.py:122,126,169,572

# Broker data adapters (pd.tz_localize("Asia/Kolkata"))
broker/aliceblue/api/data.py:714,916,948
broker/compositedge/api/data.py:559,560,579,580,692,696,732
broker/deltaexchange/api/order_api.py:158,202
broker/definedge/api/data.py:853
broker/dhan/api/data.py:160-190, 334, 356, 451-599
broker/dhan_sandbox/api/data.py:160-641
broker/firstock/api/data.py:1061-1065
broker/fivepaisa/api/data.py:677,836,996,1054
broker/fivepaisaxts/api/data.py:558-732
broker/flattrade/api/data.py:668,669
broker/groww/api/data.py:225-893
broker/ibulls/api/data.py:558-732
broker/jainamxts/api/data.py:562-785
broker/motilal/api/data.py:276,439,637
broker/rmoney/api/data.py:632-832
broker/tradejini/api/data.py:813,815,884,888
broker/wisdom/api/data.py:558-732
broker/zerodha/api/data.py:186,306,433,553
```

## Blast radius

- **Phase 4 (venue/session/timezone normalization)** — the venues table
  gets an IANA `timezone_name` column (Phase 2a already carries one).
  Services resolve the timezone off the venue record. This inventory
  enumerates the call sites that must be migrated.
- **Phase 1a (domain)** — invariant §6: "No new code may reference
  `Asia/Kolkata` or `IST` as a literal." Existing code is untouched
  until its migrating phase.
- **Phase 9 (canary)** — no strict IST-literal lint is added yet; a
  ruff rule could be added post-Phase-4 once the pool of exceptions is
  finite.
- Broker adapters keep their IST handling under Track A — they are
  talking to Indian brokers and IST is semantically correct there.
  The inventory is needed for the venue table's timezone wiring, not
  for ripping out the broker-level conversions.

Invariant: new code must resolve tz from a venue record, not from a
string literal.
