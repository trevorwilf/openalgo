# /api/v2 — market-agnostic API surface (Phase 6 skeleton)

> **Status:** skeleton. Stable by design — the normalized DTOs come
> straight from `domain/` (Phase 1a) and will not change shape. Several
> endpoints currently proxy to `/api/v1` services for their data until
> the underlying normalization phases (Phase 3c, 4, 7) wire deeper.

## Feature flag

The entire surface is gated by the env variable `API_V2`. When unset or
falsy, `/api/v2/*` requests return **404**. Turn it on with:

```bash
API_V2=1 uv run app.py
```

`/api/v1` is unaffected whether `API_V2` is on or off.

## Authentication

Same as `/api/v1`: include `apikey` in the JSON body, query string, or
the `X-API-KEY` header. The key resolves the active broker session; no
additional v2-specific credentials.

## Envelope

### Success

```json
{
  "data": <payload>
}
```

### Error

```json
{
  "error": {
    "code": "unsupported_capability",
    "message": "broker 'zerodha' does not support order_type=TRAILING_STOP",
    "details": {
      "broker_code": "zerodha",
      "capability_name": "order_type=TRAILING_STOP"
    }
  }
}
```

Distinct from `/api/v1`'s `{"status": "error", "message": "..."}` shape.
Structured so clients can branch on `error.code` instead of string
matching `error.message`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/capabilities` | Rich `BrokerCapabilities` for the active broker |
| GET | `/api/v2/instruments/search` | Search instruments by venue / asset class / query |
| GET | `/api/v2/instruments/<id>` | Single instrument + identifiers |
| POST | `/api/v2/quotes` | Batch quote fetch for a list of `InstrumentRef` |
| POST | `/api/v2/bars` | OHLCV history for a single `InstrumentRef` |
| POST | `/api/v2/orders` | Place a `NormalizedOrderRequest` (translated to legacy Indian wire format for broker dispatch) |
| GET | `/api/v2/positions` | Positions, wrapped in v2 envelope |
| GET | `/api/v2/balances` | Balances, wrapped in v2 envelope |

## `InstrumentRef` shapes

Every endpoint that takes or returns an instrument uses the normalized
`InstrumentRef` (Phase 1a, mirrored on the frontend in
`frontend/src/types/capabilities.ts`).

Exactly one of:

```json
// Shape 1 — canonical UUID
{"instrument_id": "<uuid>"}

// Shape 2 — venue_code + canonical_symbol
{"venue_code": "NSE", "canonical_symbol": "RELIANCE"}

// Shape 3 — external identifier + optional broker / venue narrowing
{
  "identifier_type": "BROKER_TOKEN",
  "identifier_value": "738561",
  "venue_code": "NSE"
}
```

Additional context: `broker_code` may appear as an optional narrowing
hint on Shape 3 (same broker, venue-specific token).

## Examples

### Capabilities

```http
GET /api/v2/capabilities
```

```json
{
  "data": {
    "broker_code": "zerodha",
    "broker_display_name": "Zerodha",
    "market_families": ["IN_STOCK"],
    "supported_venue_codes": ["NSE", "BSE", "NFO", ...],
    "supported_order_types": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"],
    "supported_time_in_force": ["DAY"],
    ...
  }
}
```

### Place an order

```http
POST /api/v2/orders
Content-Type: application/json

{
  "apikey": "...",
  "instrument": {"venue_code": "NSE", "canonical_symbol": "RELIANCE"},
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": "1",
  "quantity_unit": "WHOLE",
  "price": "2900.00",
  "time_in_force": "DAY"
}
```

The request is translated to the legacy Indian shape (via
`domain.translators.normalized_order_to_legacy_fields`) and dispatched
through the same `services.place_order_service.place_order_with_auth`
v1 uses. Broker modules are not touched.

On success:

```json
{
  "data": {
    "order_id": "240421000000042",
    "status": "submitted",
    "instrument": {
      "instrument_id": null,
      "venue_code": "NSE",
      "canonical_symbol": "RELIANCE"
    },
    "legacy": { ...unchanged v1 broker response for audit... }
  }
}
```

## `/api/v1` parity guarantee

v2's existence does not change any `/api/v1` behavior. The Phase 0
parity harness runs against every phase boundary and is required to
pass with `API_V2` both off and on.

## Future work

- Position / balance normalization into `NormalizedPosition` /
  `NormalizedBalance` (currently wrapped, not transformed).
- Quote and bar response normalization into `NormalizedQuote` /
  `NormalizedBar` (currently embedding v1 payloads inside the v2 envelope).
- Streaming endpoint (`/api/v2/stream`) is out of scope for this phase.
- OpenAPI doc generation (currently `doc=False`; flask-restx swagger
  output needs per-endpoint `@api.expect` / `@api.marshal_with`
  decorators to be useful).
