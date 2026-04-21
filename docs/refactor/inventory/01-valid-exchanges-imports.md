# Inventory 01 — `VALID_EXCHANGES`, `VALID_PRODUCT_TYPES`, `VALID_PRICE_TYPES` import sites

## Summary

`utils/constants.py` defines three Indian-shaped lists that act as the
validation boundary for every order-placement, quote, history, depth, and
basket path in the codebase. Any code wanting to accept a new market family
(US equities, European auction, crypto perpetuals) bumps into these lists
first — they are `["NSE", "NFO", "MCX", ...]` and `["CNC", "NRML", "MIS"]`
and `["MARKET", "LIMIT", "SL", "SL-M"]` with no concept of a session, a
TIF other than DAY, or a quantity unit other than WHOLE/LOTS.

Two blueprints (`blueprints/chartink.py`, `blueprints/strategy.py`) shadow
the constant with their own narrower copies, which must also be retired.

## Raw citations

```
utils/constants.py:48        VALID_EXCHANGES = [... 11 Indian exchange codes ...]
utils/constants.py:67        VALID_PRODUCT_TYPES = [PRODUCT_CNC, PRODUCT_NRML, PRODUCT_MIS]
utils/constants.py:75        VALID_PRICE_TYPES = [PRICE_TYPE_MARKET, PRICE_TYPE_LIMIT, PRICE_TYPE_SL, PRICE_TYPE_SLM]

# Local redefinitions (shadowing the canonical lists)
blueprints/chartink.py:65    VALID_EXCHANGES = ["NSE", "BSE"]
blueprints/chartink.py:464,503,537   (usage)
blueprints/strategy.py:69    VALID_EXCHANGES = ["NSE", "BSE", "NFO", "CDS", "BFO", "BCD", "MCX", "NCDEX"]
blueprints/strategy.py:569,608,642   (usage)

# Imports of the canonical lists
utils/api_analyzer.py:23-25,126-245   VALID_EXCHANGES, VALID_PRICE_TYPES, VALID_PRODUCT_TYPES (3 validation blocks)
restx_api/data_schemas.py:5,43,48,61,106,116,141,161,203,214   VALID_EXCHANGES
restx_api/schemas.py:3,25,58,90,135,173,211,294,313,327   VALID_EXCHANGES (+ CRYPTO_EXCHANGES at 3)
services/basket_order_service.py:13-15,93,106,110            VALID_* trio
services/depth_service.py:6,26                                VALID_EXCHANGES
services/history_service.py:9,44                              VALID_EXCHANGES
services/margin_service.py:7,58,74,81                         VALID_EXCHANGES + VALID_PRICE_TYPES + VALID_PRODUCT_TYPES + VALID_ACTIONS
services/place_order_service.py:12-14,84,98,102               VALID_* trio
services/place_smart_order_service.py:16-18,85,98,102         VALID_* trio
services/quotes_service.py:6,26                               VALID_EXCHANGES
services/split_order_service.py:13-15                         VALID_* trio (import only; usage follows)
```

## Blast radius

- **Phase 1a (domain)** — introduces `MarketFamily`, `AssetClass`,
  `OrderType`, `TimeInForce`, `Session`, `QuantityUnit` and
  `translators.legacy_exchange_to_venue_code`,
  `translators.legacy_product_to_order_attrs`,
  `translators.legacy_pricetype_to_order_type`. No caller migrations.
- **Phase 1b (plugin capabilities)** — `BrokerCapabilities` exposes the
  per-broker allowed set. Legacy defaults inferred from
  `broker_type`, so existing plugins keep working.
- **Phase 3a (resolver + quote/history migration)** — behind
  `RESOLVER_V2`, `services/quotes_service.py` and
  `services/history_service.py` migrate validation from `VALID_EXCHANGES`
  to capability-driven checks.
- **Phase 6 (`/api/v2`)** — new v2 handlers never import these lists;
  they accept normalized types directly.
- **Phase 9 (flags/canary)** — these lists become deprecated. Legacy
  blueprints (`chartink.py`, `strategy.py`) retain their narrow copies
  for v1 parity.

Invariant: new code MUST NOT import these three lists. See
`CLAUDE.md` — "Market-agnostic refactor (in progress)".
