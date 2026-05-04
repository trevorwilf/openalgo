# ADR 0032 — v8 scope placeholder

* **Status:** Proposed
* **Date:** 2026-05-04
* **Context:** v7 closed (see
  [`v7-FINAL-complete.md`](../refactor/v7-FINAL-complete.md));
  this ADR pins the v8 scope so the next cycle starts with a
  documented entry point in the ADR ledger.

## Decision

v8 picks up where v7 left off, focusing on the items v7
explicitly deferred:

1. **Real Schwab API integration** — official Schwab Trader API
   wiring for `broker/schwab/`. Replaces the v7 capability
   scaffold with live OAuth + order/quote/bar/stream adapters.
   Blocked on operator obtaining official API access.

2. **Real Webull API integration** — same shape as Schwab for
   `broker/webull/`.

3. **Real Alpaca production verification** — beyond the v7
   framework-readiness tests, run real-API contract suites
   (place order, modify, cancel, stream) against the operator's
   paper account on Mondays. Tests assert byte-identical request
   payloads where v1 ↔ Alpaca contract drift is forbidden.

4. **T-25 frontend page-level expansion** — populate
   `frontend/src/{us,eu,uk}/pages/` with the per-region
   components that mirror `india_legacy/`. ~393 net-new
   TSX/TS files; phased per-page delivery (Dashboard first,
   then OrderBook, then Positions, etc.). The `RegionContent`
   router from v7 Phase 5 is the integration point.

5. **Active migration of v1-lane callers to `SymTokenV1Read`** —
   the v1 view + ORM model exist (v7 Phase 4-bis-4 / 4-bis-6).
   Migrate `services/symbol_service.py` and
   `services/instruments_service.py` v1 paths to query the view
   instead of the table. Closes the "view exists but nobody
   uses it" gap.

6. **Real EU / UK options chain market-data adapters** — the
   provider classes exist (v7 Phase 6-bis); needs Eurex /
   Euronext / ICE Europe data feed credentials to wire chain
   retrieval.

7. **Page-level applications of `RegionContent`** — the
   component exists (v7 Phase 5); pages opt in via per-region
   children. v8 ships at least one production page using the
   router as a pattern reference.

8. **`/api/v1/*` removal** — coordinated operator-controlled
   sunset window. v5 Phase 8 added the `Deprecation` /
   `Sunset` headers; v8 closes by removing the v1 routes after
   the sunset date passes.

## What v8 explicitly defers (out-of-scope)

* Multi-broker-per-instance deployment (ADR 0001 single-tenant
  locked).
* APAC ex-India / LATAM region plugins.
* OpenTelemetry / Prometheus metrics backend upgrade.

## v8 closing invariants (proposed)

To be expanded once v8 phases land. Initial sketch:

* **v8-A:** Real Schwab plugin's `api/` package implements the
  full broker contract (auth, account, order, quote, bar,
  stream, sync) without `legacy_v1` imports.
* **v8-B:** Real Webull plugin same as v8-A.
* **v8-C:** `services/symbol_service.py` v1 lookup paths query
  through `SymTokenV1Read` (or the `symtoken_v1` view via raw
  SQL).
* **v8-D:** US sibling has at least Dashboard + OrderBook +
  Positions pages rendering through `/api/v2/*` with the USD
  formatter.

## References

* v7 closing report:
  [`docs/refactor/v7-FINAL-complete.md`](../refactor/v7-FINAL-complete.md)
* v6 closing report:
  [`docs/refactor/v6-FINAL-complete.md`](../refactor/v6-FINAL-complete.md)
* Expert 3 source documents under repo root.
