# ADR 0010 — Capability-driven frontend, MCP defaults, and currency propagation

Status: accepted (Phase 5, market-agnostic v2)
Date: 2026-04-25

## Context

The expert reviews flagged three places where the frontend, the MCP
server, and the Telegram service silently emitted Indian defaults even
when the active broker plugin said otherwise:

* `frontend/src/hooks/useSupportedExchanges.ts` always fell back to
  `['NSE','BSE','NFO','BFO','CDS','MCX','CRYPTO']` when capabilities
  failed to load.
* `frontend/src/lib/utils.ts` and the order-form components mapped
  the broker name to ₹ / $ instead of reading
  `BrokerCapabilities.base_currency` (or the instrument's currency).
* `mcp/mcpserver.py` defaulted every tool's `exchange="NSE"` and
  `product="MIS"`, producing invalid orders for non-India brokers.
* `services/telegram_bot_service.py` used `broker in CRYPTO_BROKERS`
  as the only currency signal.

Phase 5 closes these by routing every default through the capability
surface, with a structured error path when the data needed to render
isn't available.

## Decision

### `useSupportedExchanges` is region-aware

The hook now treats the legacy `['NSE','BSE','NFO',...]` fallback as
**India-only**. Logic:

```
indiaShaped = capabilities is null OR supported_regions contains "india" OR supported_regions is empty

supported = capability venue codes
            ?? (allowLegacyFallback && indiaShaped ? legacy_fallback : [])

defaultExchange = first(supported) ?? (isCrypto ? "CRYPTO"
                                       : indiaShaped ? "NSE"
                                       : "")
```

A non-India broker (e.g. Alpaca) NEVER receives the legacy fallback.
When its capability list lacks venue codes, the hook returns empty
arrays and consumers render an "unavailable" state.

The Vitest suite at `frontend/src/hooks/useSupportedExchanges.test.ts`
gains:

* `non-India broker uses its own venue codes`
* `non-India broker with no venue codes does NOT fall back to NSE`
* `legacy India plugin (no supported_regions field) still falls back`
* `explicit india supported_regions falls back when capabilities lack venue codes`

### MCP defaults route through capability lookup

`mcp/mcpserver.py` now exposes:

```python
@lru_cache(maxsize=1)
def _connected_broker_caps() -> dict | None: ...

def _is_india_broker() -> bool: ...

def _resolve_default(value, india_default, *, field_name) -> str:
    if value is not None:
        return value
    if _is_india_broker():
        return india_default
    raise ValueError(
        f"{field_name!r} is required when the connected broker is non-India. "
        "Read /api/v2/capabilities/<broker> for the supported values."
    )
```

`place_order`, `place_smart_order`, and `get_quote` now declare their
exchange/product parameters as `str | None = None` and call
`_resolve_default`. Indian brokers see the same NSE/MIS substitutes as
before; non-India brokers without explicit values receive a
structured `missing_required_field` JSON envelope. Tests can force
behavior through `MCP_FORCE_REGION_FOR_TESTS`.

The remaining MCP tool definitions (`place_options_order`,
`place_options_multi_order`, etc.) continue to require the values
explicitly today; they are not yet using `_resolve_default` because
they already make the parameters required, which is the desired
non-India behavior.

### Currency propagation in Telegram bot

`TelegramBotService._cs` looks up `base_currency` from the broker's
`BrokerCapabilities` and maps the currency code to a glyph
(`INR→₹`, `USD→$`, `EUR→€`, `GBP→£`, `JPY→¥`, `BTC→₿`, etc.).
Falls back to:

* `$` for `broker_type == "crypto"`,
* `₹` for legacy India brokers without capabilities or with
  `supported_regions` containing "india",
* `$` for any other unknown plugin (default-safe non-India).

### New `/api/v2/regions` endpoints

`restx_api/v2/regions.py` exposes:

* `GET /api/v2/regions` — every loaded region (full v2 shape).
* `GET /api/v2/regions/<region_code>` — single region metadata.
* `GET /api/v2/regions/<region_code>/flow_defaults` — exchanges,
  products, option underlyings, lot sizes, and a default schedule.
  Returns the disabled-shape (empty lists, `flow_templates_enabled:
  false`) when the region's `feature_flags.flow_templates_enabled` is
  false. India returns its actual templated defaults.

### Region loader path resolution

`utils/region_loader._region_root_path` now searches the Flask app
root, the current working directory, and the repo root in order. This
lets test apps discover the shipped `market_regions/` plugins
without each test conftest having to chdir.

## Consequences

* **No silent NSE/NFO leakage** in non-India frontends. The trading
  UI either renders a populated capability list or an unavailable
  state.
* **Every UI currency comes from the broker capability**, not a name
  pattern match. Adding a new currency means adding a row to the
  symbol map (and the `Currency` enum).
* **MCP non-India usage requires explicit values.** Operators who
  point Claude Desktop at an Alpaca instance get a structured error
  pointing them to `/api/v2/capabilities/<broker>` instead of a
  silent invalid order.
* **Future regions ship as a single JSON file.** A new region's
  flow defaults are read from the plugin; no Python edits required.

## Alternatives considered

* **Pass `region_code` through the URL on every v2 endpoint.**
  Rejected — single-broker per instance per ADR 0001 means the
  region is implicit from the active broker.
* **Drop the legacy India fallback entirely.** Rejected — would
  break the login screen and existing Indian deployments. The
  fallback is gated by India-shape detection so it only fires for
  the cases that need it.

## References

* ADR 0001 — Single-broker per deployment
* ADR 0006 — Literal scanner and fail-closed capabilities
* ADR 0007 — Region plugin schema v2
* `frontend/src/hooks/useSupportedExchanges.ts`
* `mcp/mcpserver.py` — `_resolve_default`
* `restx_api/v2/regions.py`
