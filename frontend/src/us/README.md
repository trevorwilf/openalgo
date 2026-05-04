# US region frontend sibling

Mirror of `frontend/src/india_legacy/` for US-region brokers
(Alpaca / future Schwab / Webull). Builds region-specific UI on
top of the v2 capability hooks + `/api/v2/*` endpoints.

## Status

Scaffolding only. The directory structure mirrors
`india_legacy/`:

- `pages/` — page-level components (Dashboard, OrderBook,
  Positions, etc.). Currently empty; pages render via the
  shared promoted components which read capabilities from the
  broker store.
- `components/` — region-specific UI primitives.
- `api/` — region-specific API clients (US doesn't use the v1
  India endpoints; everything goes through `/api/v2/*`).
- `hooks/` — region-specific hooks (e.g.
  `useRegulatoryDisclosures` for FINRA / Reg-T).
- `lib/` — utility modules.

## Mounting

The top-level router (post-T-25) selects this sibling for
sessions where the active broker's primary region is `"us"`.
`_mock_schwab_like` / `_mock_webull_like` / `alpaca` /
`schwab` / `webull` all resolve here.

## What lives here vs. the shared layer

* **Lives here**: anything that's US-specific in a way the
  capability layer can't express today. Examples: settlement-T+1
  copy ("Settles on the next trading day"), Reg-T disclaimer
  text, $0.00 commission badge.
* **Lives in the shared layer**: anything that's truly region-
  agnostic. Examples: order entry form (driven by capability
  hooks), positions table (column visibility from capabilities),
  P&L tracker (renders in active venue tz).

## Currency formatting

Use `formatCurrencyAmount(amount, "USD")` from
`@/lib/format/currency`. Never default to INR — the canonical
formatter requires explicit currency per v6 Phase 5.
