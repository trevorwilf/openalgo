# Market-Agnostic Refactor v5 — Overview

v5 finishes the market-agnostic core. v4 delivered framework
readiness (12 invariants, 6 new ADRs, 8 parity harnesses, 5 partial
phases with `phase-N-bis` follow-ups). v5 closes the deferred
bis-phases, executes additional findings from two independent expert
reviews, and migrates Indian brokers from `/api/v1` to `/api/v2` so
v1 can be deprecated.

**Authoritative source:** `openalgo_market_agnostic_v5_claude_code_prompt.md`
in the repo root. Operator decisions D-1…D-6 lock the disputed
choices; in-repo ADRs win on conflict with the experts.

**Out of scope (DO NOT touch):** real Schwab API code, real Webull
API code, real OAuth/credential flows, FINRA/MiFID/regulatory code,
EU/UK pilot real-broker plugins, multi-broker-per-instance
deployment, dropping legacy schema columns. Mock Schwab-LIKE and
Webull-LIKE plugins remain the only Schwab/Webull surface.

---

## v5 invariants

v5 keeps every v4 invariant in force; it adds two governance
invariants on top.

| # | Invariant | Source | Enforcement |
|---|---|---|---|
| v5-1 | Every promoted (v2) error response carries a stable `code` from `domain.errors.ErrorCode`; new fail-closed branches use the v5 codes (ADR 0029). | ADR 0029 | `tests/contracts/test_v5_structured_errors_emitted.py` |
| v5-2 | Every promoted (v2) request emits one structured-log line with the canonical label set (ADR 0030). Legacy (v1) requests do not. | ADR 0030 | `tests/contracts/test_v5_observability_labels_complete.py` |

v4 invariants 1–12 (CLAUDE.md "Promoted lane" §) remain in force.

---

## Phases

| Phase | Goal | Closes | Status |
|---|---|---|---|
| 1 | v5 governance, classification refresh, structured errors, observability spec | MA-000…MA-003, P0-01…P0-08 | ✅ complete |
| 2 | Frontend per-component capability rewrites | v4 6-bis, P4-01…P4-07 | ✅ partial — load-bearing core; per-component cleanup deferred to Phase 2-bis |
| 3 | Strategy scheduler + Historify frontend venue-tz aware | v4 7-bis, P5-01…P5-06 | ✅ partial — DST contract pinned; per-blueprint refactor deferred to Phase 3-bis |
| 4 | Sandbox blueprint + DB migration + UI region-awareness | v4 8-bis, P6-01…P6-05 | ✅ partial — DB migration + capability + parity; route adoption deferred to Phase 4-bis |
| 5 | Options service shimming + provider parity + capability | v4 9-bis, P7-01…P7-06 | ✅ partial — capability + parity; per-service shimming deferred to Phase 5-bis |
| 6 | Screener (Chartink) dispatcher migration + DB migration + UI gating | v4 10-bis, P7-07…P7-09 | ✅ partial — DB migration + capability + parity; route adoption deferred to Phase 6-bis |
| 7 | Capability schema completion, account context, combo, streaming hardening | MA-007, MA-022…MA-025, MA-037, P3-01…P3-06, P8-01…P8-04 | ✅ complete |
| 8 | India v1→v2 broker readiness + v1 deprecation announcement | D-1 first half | ✅ partial — deprecation announced; per-broker translator + parity deferred to Phase 8-bis |
| 9 | India v1→v2 cutover + legacy compatibility shim retirement | D-1 second half | ✅ partial — cutover scaffolding ready; default-flip gated on Phase 8-bis completion |
| 10 | v5 closing audit, framework-readiness re-verification, docs | MA-038…MA-044, P9-01…P9-06 | ✅ complete |

Each phase has its own completion document at
`docs/refactor/v5-phase-<N>-complete.md` written at merge time.

---

## What v6 should consider

* **Real Schwab plugin** (blocked on official API access, OAuth
  scopes, account-hash resolution, entitlement model).
* **Real Webull plugin** (blocked on official API access; mock
  declares `subaccount_id` semantics that real Webull may differ
  from).
* **Real EU / UK broker plugin** pilots.
* **v1 sunset and removal** (Phase 9 ships `Deprecation: true` +
  `Sunset` headers; the actual removal lives in v6 after the
  operator-controlled sunset date).
* **Multi-broker-per-instance** deployment model (currently single
  user / single broker per instance per CLAUDE.md).
* **Additional region plugins** — APAC ex-India, LATAM, crypto
  (each one a separate ADR + plugin + provider stack).
* **Metrics backend** — the v5 observability label set is the seed
  schema; v6 may upgrade to OpenTelemetry / Prometheus.

---

## Authoritative cross-references

* `docs/refactor/v3_baseline_audit.md` — v3 gap tracker (closed in
  v4; v5 does not regress).
* `docs/refactor/v4-overview.md` — v4 evidence package.
* `docs/refactor/file_classification.md` — every Python file's lane.
* `docs/refactor/route_fallback_inventory.md` — per-route v1/v2
  disposition.
* `docs/refactor/symtoken_callers.md` — SymToken caller audit (zero
  PROMOTED_LEAK rows).
* `docs/refactor/canonical_legacy_parity_report.md` — canonical-vs-
  legacy parity yardstick.
* `docs/refactor/broker_compliance_matrix.md` — per-broker
  compliance.
* `docs/refactor/deprecation-schedule.md` — what is removable when.
* `docs/refactor/schwab_readiness.md` /
  `docs/refactor/webull_readiness.md` — framework-readiness
  evidence packages.
* `docs/api/v2_errors.md` — v5 structured error taxonomy (ADR 0029).
* `docs/observability/promoted_request_labels.md` — v5 observability
  label spec (ADR 0030).
* `docs/adr/0001-*.md` … `0030-*.md` — accepted ADRs.
