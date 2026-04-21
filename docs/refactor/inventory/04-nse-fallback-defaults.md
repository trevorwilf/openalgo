# Inventory 04 — Fallback default of `"NSE"` across the codebase

## Summary

`"NSE"` is the implicit market when input is missing or ambiguous.
`blueprints/python_strategy.py` uses it in scheduler checks; `blueprints/flow.py`
hardcodes it as a trigger default; most broker `mapping/order_data.py`
modules (compositedge, wisdom, ibulls, iifl, fivepaisaxts, jainamxts,
motilal, iiflcapital) default exchange to `"NSE"` for equity holdings;
many broker `api/data.py` modules fall back to `"NSE"` when an incoming
symbol carries no exchange tag; example strategies and example scripts
all hardcode `exchange = "NSE"`.

The dominant risk: a non-Indian broker hitting one of these defaults
silently routes an order to the wrong venue. Fix is per-call — there is
no single constant — and every phase that touches a caller must verify.

## Raw citations

```
# Core blueprints
blueprints/flow.py:240          exchange=trigger_data.get("exchange", "NSE")
blueprints/python_strategy.py   does not hardcode NSE directly; exchange
                                 comes from strategy config. Flagged here
                                 because schedule/holiday paths assume
                                 Indian exchanges via market_calendar_db.

# Broker mapping/order_data (equity holdings default)
broker/compositedge/mapping/order_data.py:399     exchange = "NSE"  # Default to NSE for equity holdings
broker/wisdom/mapping/order_data.py:411           exchange = "NSE"  # Default to NSE for equity holdings
broker/ibulls/mapping/order_data.py:399           exchange = "NSE"  # Default to NSE for equity holdings
broker/iifl/mapping/order_data.py:399             exchange = "NSE"  # Default to NSE for equity holdings
broker/fivepaisaxts/mapping/order_data.py:399     exchange = "NSE"  # Default to NSE for equity holdings
broker/jainamxts/mapping/order_data.py:399        exchange = "NSE"  # Default to NSE for equity holdings
broker/motilal/mapping/order_data.py:404,489      exchange = holdings.get("exchange", "NSE")
broker/iiflcapital/mapping/order_data.py:309      exchange = "NSE"
broker/aliceblue/mapping/order_data.py:120        exchange = "NSE" if nse_symbol else ("BSE" if bse_symbol else "NSE")

# Broker groww (extensive NSE-default surface)
broker/groww/api/data.py:181,1096,1115,1865,1869
broker/groww/api/order_api.py:1210,1535,2230,3079
broker/groww/mapping/order_data.py:128,342,445,464,494,512,577,584,766,780,901
broker/groww/streaming/groww_adapter.py:508,530

# Broker api/data (fallback on missing exchange)
broker/angel/api/data.py:99,222,348,682
broker/aliceblue/api/data.py:644
broker/definedge/api/data.py:62,445
broker/flattrade/api/data.py:102,356,440,527
broker/firstock/api/data.py:173,354,642,977
broker/motilal/api/data.py:276,439,637
broker/paytm/api/data.py:115
broker/paytm/api/order_api.py:152,250
broker/nubra/api/order_api.py:457
broker/nubra/api/nubrawebsocket.py:570,573
broker/zebu/api/data.py:101,355,421,503
broker/zerodha/api/data.py:186,306,433,553
broker/zerodha/streaming/zerodha_adapter.py:298
broker/dhan_sandbox/streaming/dhan_websocket.py:712,934
broker/fyers/streaming/fyers_adapter.py:168,180
broker/fyers/streaming/fyers_mapping.py:481
broker/fyers/streaming/fyers_websocket_adapter.py:763
broker/samco/streaming/samco_adapter.py:192,299

# Option routing: NSE quote for NFO options, BSE for BFO
services/option_symbol_service.py:591    quote_exchange = "NSE" if exchange.upper() == "NFO" else "BSE"
services/option_chain_service.py:258     quote_exchange = "NSE" if exchange.upper() == "NFO" else "BSE"
services/options_multiorder_service.py:75  same pattern

# Download / example scripts
download/sqlite_downloader.py:63
download/ieod.py:116
strategies/examples/simple_ema_strategy.py:30
examples/python/supertrend.py:15
examples/python/ema_crossover.py:16
examples/python/cagr_heatmap.py:114
restx_api/ticker.py:151
```

## Blast radius

- **Phase 1a (domain)** — `InstrumentRef` forces an explicit venue;
  there is no "default venue". Callers that previously defaulted must
  now resolve through the resolver.
- **Phase 3a (resolver)** — when a caller still passes `(symbol,
  exchange)` to the resolver, the broker capability set is consulted:
  if `NSE` is not a supported venue for the active broker, the call
  raises `ResolverMiss` rather than silently routing.
- **Phase 5 (frontend)** — default selections come from the broker
  capability set (first supported trading venue), not a hardcoded
  `NSE`. See `frontend/src/hooks/useSupportedExchanges.ts:70-73`.
- **Broker mapping defaults** are NOT refactored under Track A —
  they operate inside Indian-broker code paths and the default is
  semantically correct for those brokers. The inventory is needed so
  that a future non-Indian broker's mapping module doesn't accidentally
  inherit the pattern.

Invariant: new code must either require an explicit venue or resolve
through `InstrumentResolver`. No new `exchange=exchange or "NSE"`.
