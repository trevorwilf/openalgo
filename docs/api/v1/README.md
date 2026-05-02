# /api/v1 — Legacy India lane

> **Status:** India-only legacy lane (per ADR 0005). Stable but
> deprecated; every `/api/v1/*` response carries
> `Deprecation: true` + `Sunset: <date>` headers. Operators control
> the actual sunset date via `OPENALGO_V1_SUNSET_DATE` (Phase 9 T-33);
> when unset, no enforcement is applied.
>
> The lane is **only mounted when the India region plugin is loaded**
> (Phase 9 T-23 logical conditional). Non-India deployments don't
> mount these routes at all — direct request returns 404 Not Found
> at the route layer (not 410 Gone — 410 is reserved for the
> sunset-passed enforcement path).

## What lives in v1

* India-shaped schemas (`restx_api/schemas.py`, `data_schemas.py`,
  `account_schema.py`).
* India-shaped service entry points (Phase 3 migrated 8 to be
  region-aware while preserving v1-lane behavior).
* India venues: `NSE`, `BSE`, `NFO`, `BFO`, `CDS`, `BCD`, `MCX`,
  `NCDEX`, `NSE_INDEX`, `BSE_INDEX`, `CRYPTO`.
* India products: `MIS`, `CNC`, `NRML`.
* India price types: `MARKET`, `LIMIT`, `SL`, `SL-M`.
* INR base currency, IST timestamps.

## Endpoint reference

The full per-endpoint reference for v1 lives at the API documentation
top level (T-24 keeps the existing endpoint paths stable for
backward-compatible deep links from external integrations):

* [`docs/api/account-services/`](../account-services/) — account / funds / orderbook / tradebook / holdings / positionbook / margin
* [`docs/api/analyzer-services/`](../analyzer-services/) — analyzer mode (paper-trading) toggles
* [`docs/api/market-calendar/`](../market-calendar/) — holidays + timings + checkholiday
* [`docs/api/market-data/`](../market-data/) — quote / depth / history / ticker
* [`docs/api/options-services/`](../options-services/) — option_chain / option_greeks / option_symbol / options_multiorder / options_order
* [`docs/api/order-information/`](../order-information/) — orderstatus / openposition
* [`docs/api/order-management/`](../order-management/) — placeorder / placesmartorder / modifyorder / cancelorder / cancelallorder / closeposition / basket_order / split_order
* [`docs/api/symbol-services/`](../symbol-services/) — symbol / search / instruments / intervals
* [`docs/api/websocket-streaming/`](../websocket-streaming/) — subscribe_ltp / subscribe_quote / subscribe_depth

## Migration to /api/v2

* `/api/v2` is the region-neutral lane — see [`../v2/README.md`](../v2/README.md).
* Per-broker `API_V2_<BROKER>=1` flips a broker over from v1 to v2.
* Phase 6 verified all 30 India broker translators produce
  bit-identical output on both lanes (see
  [`docs/refactor/v6-translator-parity-status.md`](../../refactor/v6-translator-parity-status.md)).
* For non-India brokers, v2 is the only lane. v1 returns 410 Gone.

## Sunset machinery

Set `OPENALGO_V1_SUNSET_DATE=YYYY-MM-DD` to enforce a hard cutover.
After that date every `/api/v1/*` request returns:

```json
{
  "status": "error",
  "code": "v1_sunset_passed",
  "message": "/api/v1/* was sunset on YYYY-MM-DD; the endpoint is no longer available...",
  "sunset_date": "YYYY-MM-DD"
}
```

The default is **unset** — no enforcement, just the
`Deprecation: true` + `Sunset:` headers as a soft announcement.
