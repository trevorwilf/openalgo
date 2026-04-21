# Inventory 02 — `SymToken` and `get_token` usage sites

## Summary

`SymToken` (`database/symbol.py:33`) is the single table that every broker
sync destroys and rewrites at login. Its identity key is `(symbol,
exchange)` — a pair with no broker provenance, which makes cross-broker
coexistence impossible today. Every service, most blueprints, and every
broker's `mapping/order_data.py` and `database/master_contract_db.py` read
from it via `SymToken.query` or `get_token(symbol, exchange)`.

The table is **read-only** from Phase 2 onward. New code reads from the
Phase 2a tables (`instruments`, `broker_instrument_map`,
`instrument_identifiers`). `SymToken` becomes a compat shim retired only
after parity passes in Phase 9.

## Raw citations

See the grep dump at
`tool-results/toolu_01P4PM6XzFrnHsZz5WXovUs5.txt` for the exhaustive list
(~1200 hits across ~110 files). High-traffic callers:

```
# Schema and helpers
database/symbol.py:33                    SymToken table definition
database/symbol.py:57,118,273,323        search helpers
database/token_db.py                     legacy cache layer (get_token, enhanced variants)
database/token_db_enhanced.py:246,273,299   IST-tagged cache stats

# Direct consumers via SymToken.query
blueprints/custom_straddle.py:10,97,99-102
blueprints/flow.py:697,710-736
blueprints/search.py:75,...
websocket_proxy/mapping.py:1,47          get_token(symbol, exchange)

# Destructive sync (every broker)
broker/*/database/master_contract_db.py  delete_symtoken_table() followed by bulk INSERT

# Resolver paths used across services
services/quotes_service.py               -> token_db.get_token
services/history_service.py              -> token_db.get_token
services/depth_service.py                -> token_db.get_token
services/place_order_service.py          -> token_db.get_token
services/option_chain_service.py         -> SymToken / token_db
services/option_symbol_service.py        -> SymToken / token_db
services/options_multiorder_service.py   -> SymToken / token_db
services/iv_chart_service.py             -> SymToken via helpers
services/straddle_service.py             -> SymToken via helpers
```

## Blast radius

- **Phase 2a (additive schema)** — adds `venues`, `instruments`,
  `instrument_identifiers`, `broker_instrument_map`,
  `instrument_sync_runs`. No reads/writes of `SymToken` from the new
  tables.
- **Phase 2b (sync pipeline)** — adds an additive, broker-tagged sync
  runner. **Does not call `delete_symtoken_table`.** Legacy sync in
  `broker/*/database/master_contract_db.py` is left byte-identical.
- **Phase 3a (resolver)** — `InstrumentResolver.resolve` falls back to
  `get_token` via `legacy_token_lookup` when the new tables don't yet
  carry the instrument; `legacy_fallback=True` is logged.
- **Phase 3b (historify)** — adds `instrument_id` columns additively;
  legacy `(symbol, exchange)` PKs remain.
- **Phase 3c (websocket)** — resolver-driven subscription lookup;
  `websocket_proxy/mapping.py:47` migrates behind a flag.
- **Phase 9 (flags/canary)** — `SymToken` flagged deprecated in the ORM
  docstring; deletion is a separate, post-refactor change.

Invariant: no new code adds columns to `SymToken` or references the
`symtoken` table name. No new `delete_symtoken_table` calls.
