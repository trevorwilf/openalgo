# ADR 0004: Analyzer/sandbox mode stays India-limited and capability-gated

- **Status:** Accepted
- **Date:** 2026-04-21

## Context

OpenAlgo's Analyzer (also called sandbox mode) is a paper-trading
environment backed by its own isolated database (`db/sandbox.db`, see
`CLAUDE.md` — "Analyzer Mode"). It implements a realistic margin system
with leverage, auto square-off at Indian exchange timings, and a ₹1
Crore (INR) virtual capital pool.

Every one of those pieces is Indian-specific:

- Margin formulas use Indian product types (`MIS`, `NRML`, `CNC`).
- Auto square-off times are hardcoded to NSE/BSE/MCX session ends.
- Virtual capital is denominated in INR.
- Settlement mechanics assume T+1 equity and daily F&O mark-to-market.

A universal analyzer — one that models US market hours, European
auctions, 24/7 crypto, multi-currency balances, varying settlement
cycles — would be a refactor the size of the core work this playbook is
already tackling.

## Decision

The analyzer stays **India-limited** throughout this refactor. It is
**capability-gated** so that brokers whose `BrokerCapabilities` declare
`supports_analyzer=False` (crypto, future non-Indian adapters) do not
expose the Analyzer UI or route orders through the sandbox service.

Concretely:

- Phase 1b's `BrokerCapabilities` model carries a boolean
  `supports_analyzer` field. Indian-family brokers default to `True`
  (inferred from their legacy `broker_type="IN_stock"`). Crypto-family
  brokers default to `False`.
- Phase 5's frontend hides the Analyzer entry point when the capability
  is false.
- Phase 7's backend short-circuits `/analyzer` routes with a
  capability-not-supported response when the active broker lacks the
  capability.
- The sandbox database, margin engine, and square-off scheduler are
  **not** generalized. No universal ledger work is in scope.

## Consequences

**Positive**

- The analyzer's India-specific math stays correct. No drift risk.
- The refactor does not need to model margin, settlement, or session
  timing for markets the core refactor is only *targeting*, not
  delivering.
- Non-Indian broker adapters land later without being blocked by an
  analyzer redesign.

**Negative**

- A user on a crypto broker cannot paper-trade through OpenAlgo's
  analyzer. They must use the broker's testnet or a separate tool.
- Any future decision to extend the analyzer to additional markets is a
  new, separately-scoped project.

## References

- `docs/adr/0001-track-a-scope.md`
- `CLAUDE.md` — "Analyzer Mode (Paper Trading)" section
- Refactor playbook §2 invariant 8 — US/EU a design target, not delivery
- Phase 1b of the refactor playbook — `BrokerCapabilities.supports_analyzer`
- Phase 7 of the refactor playbook — analyzer capability gating
