# ADR 0023 — v4 scope and advanced-feature provider contracts

* **Status:** accepted
* **Date:** 2026-04-26
* **Supersedes:** none (extends ADRs 0001–0022)

## Context

After v1, v2, and v3 of the market-agnostic refactor:

* The promoted lane scaffolding exists (BrokerOrderTranslator,
  BrokerQuoteAdapter, BrokerBarAdapter, BrokerMarketDataStream,
  BrokerOrderEventStream, AccountContext, NormalizedComboOrderRequest).
* `/api/v2` orders are fail-closed for non-India brokers.
* The literal scanner, lane-isolation tests, and SymToken caller audit
  enforce the boundary at AST and runtime levels.
* Mock Schwab-like and Webull-like plugins exist and pass the broker
  compliance harness for the order surfaces.

Two independent expert reviews evaluated the v3 deliverable and reached
the same verdict: **not safe for non-India production until further
fixes are applied.** They identified 17 confirmed gaps (tracked in
`docs/refactor/v3_baseline_audit.md`) and called out four advanced
features that remain India-coupled even after v3:

* **Sandbox** — paper trading hard-codes T+1 settlement, MIS/CNC/NRML
  product types, ₹10,00,000 initial funds, 15:15 IST square-off, no
  partial fills.
* **Options analytics** — chain, expiry, IV, OI, Greeks, straddle,
  multiorder, synthetic future, vol surface, GEX all assume Indian
  DDMMMYY/CE/PE symbology, NFO/BFO venues, weekly+monthly Indian
  expiry rules.
* **Strategy scheduler** — IST-bound cron in `python_strategy.py` and
  `strategy.py`.
* **Chartink (screener)** — webhook-parsing and order-mapping logic
  hard-coded to NSE/BSE + MIS/CNC/NRML.

These four are not appropriate for region-gating alone. They are
features that other regions also need, in their own forms. The right
abstraction is provider-pluggable contracts.

## Decision

v4 has the following scope.

### A — Close the 17 v3 baseline gaps.

Phases 2–7 systematically close every CONFIRMED and PARTIAL row in
`docs/refactor/v3_baseline_audit.md`. Each gap row is updated to FIXED
with a pointer to the closing phase by Phase 12.

### B — Hard-block v1 for non-India brokers.

The legacy `/api/v1/*` routes carry implicit India semantics in their
schemas, response shapes, and underlying services. Allowing a non-India
broker to call them is a correctness hazard. Phase 2 adds a request-
time guard returning HTTP 410 Gone with structured payload
`{"status":"error","code":"v1_unavailable_for_non_india_broker"}` for
every v1 route when the active broker's `supported_regions` excludes
`india`.

### C — Generalize four advanced features into provider contracts.

| Feature | Contract location | India provider | US provider |
|---|---|---|---|
| Sandbox (paper trading) | `services/sandbox/providers/base.py:SandboxProvider` | preserved bit-identically (T+1 / MIS-CNC-NRML / ₹10L / 15:15 IST) | mock data (T+2 equity / T+1 option / USD $100k / XNYS 16:00 close / partial fills) |
| Options analytics | `services/options/providers/base.py:OptionsProvider` | preserved bit-identically (DDMMMYY / CE-PE / NFO-BFO) | mock data (OCC OSI 21-char / Black-Scholes shared math) |
| Strategy scheduler | venue-aware schedule resolution | preserved bit-identically (Asia/Kolkata) | venue-local for promoted brokers (e.g., America/New_York for XNYS) |
| Screeners | `services/screeners/providers/base.py:ScreenerProvider` | Chartink moved into India provider, blueprint becomes thin shim | stub only — out of v4 scope per user clarification |

The dispatcher pattern fails closed: if no provider is registered for
the active broker's region, the route returns
`503 <feature>_provider_not_registered`. The frontend hides feature UI
when the active broker's capability metadata reports no supported
provider for the feature.

### D — Real Schwab / Webull broker code remains out of v4 scope.

The mock plugins exercise every promoted-lane contract end-to-end with
deterministic in-memory fixtures. Real Schwab and Webull plugin work is
blocked on human-validated official API contracts, sandbox/paper
testing, and security/compliance review.

### E — Promoted plugin schema is strict (Phase 4).

Unknown operational fields in a promoted broker's `plugin.json` are
validation errors. Missing required promoted fields block promoted
activation with a structured operator-actionable diagnostic. Legacy
India brokers retain non-strict mode for backward compatibility.

### F — Additive migrations only.

No `DROP COLUMN`, no `DROP TABLE` in v4. Sandbox, Chartink, and any
other table that gains region-aware columns adds them as nullable with
backfill defaults. Old columns retire only after one full production
release of held parity, in a future deprecation phase outside v4.

## Consequences

* The framework can host real Schwab and real Webull plugins without
  further core changes after v4 — every promoted-lane contract is
  exercised end-to-end by the mock plugins.
* India behavior remains bit-identical through every phase. Parity
  harness failures are a hard stop.
* Frontend code becomes capability-driven. No `if broker === "zerodha"`
  branches; the active broker's capability metadata drives every UI
  choice.
* Sandbox / Options / Screener gain a clean extensibility seam. Adding
  EU or UK providers in the future is a matter of writing one provider
  module per feature, not touching dispatchers or UIs.

## Alternatives considered

* **Region gating only.** Rejected: leaves the four advanced features
  India-only with no path to multi-region support. The expert reviews
  explicitly call out this approach as insufficient.
* **Replace India implementations with new generic ones.** Rejected:
  parity-protected India behavior must be preserved bit-identically. A
  ground-up rewrite breaks parity by definition.
* **Ship real Schwab / Webull plugins in v4.** Rejected: real plugin
  work requires official API validation, sandbox/paper testing, and
  security/compliance review — none of which are tractable inside the
  v4 timeline.

## Cross-references

* `docs/refactor/v3_baseline_audit.md` — the 17 gaps v4 closes.
* `docs/refactor/v4-overview.md` — phase-by-phase tracker.
* ADRs 0024–0028 (created in subsequent v4 phases) — calendar
  precedence (0024), strict promoted plugin schema (0025), sandbox
  provider contract (0026), options provider contract (0027), screener
  provider contract (0028).
