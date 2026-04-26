# ADR 0019 — SymToken classification, resolver non-India block, identifier helpers

Status: accepted (v3 Phase 3)
Date: 2026-04-25

## Context

Phase 2 made the v2 quote/bar dispatch fail-closed for non-India
brokers. The resolver they call (`services.instrument_resolution`)
only imports from `database.instruments_repo` — verified by Phase 1's
runtime import lock. But two open items remained:

1. There was no operator-readable inventory of which files import
   `database.symbol` / `database.token_db_enhanced` and whether each
   call site is "expected legacy India" or "PROMOTED leak that must
   be fixed".
2. The canonical `instrument_identifiers` table had only bare-string
   `identifier_type` callers — no `IdentifierKind` enum, no
   convenience helper to return a single instrument given an
   identifier value.

A future operator-controlled phase will migrate India traffic to the
canonical resolver. That migration is gated on parity proof — a
deterministic measurement script must be in place before the migration
can be planned.

## Decision

### SymToken caller audit

`scripts/audit/symtoken_callers.py` walks the source tree, collects
every file that imports from `database.symbol` or
`database.token_db_enhanced`, and classifies each caller using the
Phase 0 `file_classification.md` report. Output goes to
`docs/refactor/symtoken_callers.md`.

`tests/audit/test_symtoken_callers_zero_leaks.py` regenerates the
report in-process on every run and asserts the `PROMOTED_LEAK` section
is empty. As of Phase 3, every SymToken/token_db_enhanced caller is
LEGACY_INDIA or BROKER_PLUGIN; zero PROMOTED_CORE leaks.

### Resolver non-India guard

`services.instrument_resolution.resolve_instrument` only imports from
`database.instruments_repo`. Phase 3 adds
`tests/resolver/test_resolver_no_legacy_for_non_india.py` which
patches every legacy entry point (`database.token_db.get_token`,
`database.token_db.get_brexchange`,
`database.token_db_enhanced.fno_search_symbols`) and asserts none of
them is called when resolving for a non-India broker — for the
``id``, ``venue_symbol``, and ``external`` ref kinds, both for
hits and misses. Misses return ``None`` (no legacy fallback).

### IdentifierKind enum + convenience helper

`database/instruments_repo.py` adds:

```python
class IdentifierKind(str, Enum):
    ISIN = "ISIN"
    CUSIP = "CUSIP"
    SEDOL = "SEDOL"
    FIGI = "FIGI"
    RIC = "RIC"
    VENUE_SYMBOL = "VENUE_SYMBOL"
    BROKER_SYMBOL = "BROKER_SYMBOL"
    BROKER_TOKEN = "BROKER_TOKEN"
    CANONICAL_SYMBOL = "CANONICAL_SYMBOL"
```

and:

```python
def identifier_resolve_one_instrument(
    identifier_type: str | IdentifierKind,
    identifier_value: str,
    *,
    broker_code: Optional[str] = None,
    venue_code: Optional[str] = None,
) -> Optional[Instrument]:
```

Returns the single matching `Instrument` or `None` (zero or
more-than-one match). `tests/instruments_repo/test_identifier_lookup.py`
covers each kind end-to-end including the global / venue-scoped /
broker-scoped scoping semantics and the ambiguity guard.

### India parity measurement script

`scripts/audit/canonical_vs_legacy_parity.py` walks
`tests/parity/baseline/` JSON fixtures, extracts every (symbol,
exchange) pair, and writes a Markdown diff at
`docs/refactor/canonical_legacy_parity_report.md` comparing the
legacy SymToken view against the canonical Instrument view. Today
both stores are empty in dev environments so most rows are
`both_missing` — the script is the *measurement* tool, not the
migration trigger. India migration is gated on this report showing
zero `*_mismatch` rows.

## Consequences

* Operators can prove the canonical/legacy boundary at any time:
  `uv run python scripts/audit/symtoken_callers.py` plus the
  pytest sentinel.
* Future identifier-driven flows (ISIN/FIGI lookup) get a typed
  enum and a one-shot helper instead of repeated boilerplate.
* India migration to the canonical resolver has a deterministic
  parity yardstick. The migration itself remains out of scope for
  v3.

## Alternatives considered

* **Replace the resolver's `None`-on-miss return with raising
  `InstrumentNotResolvable` for non-India brokers.** Rejected for
  this phase — would cascade through the v2 dispatch code paths
  that already handle `None` correctly. The lane-isolation contract
  is enforced by static + runtime + audit tests; raising adds API
  churn without a test that today's behavior is wrong.
* **Make `identifier_resolve_one_instrument` raise on ambiguity.**
  Rejected — returning `None` lets the caller decide whether to
  retry with a narrower scope or 404; raising would force every
  caller to wrap.
* **Drop `database.token_db_enhanced` from the audit because it's
  symtoken-adjacent rather than the SymToken table itself.**
  Rejected — both modules expose the same legacy-India read paths
  and PROMOTED_CORE files must avoid both.

## References

* `scripts/audit/symtoken_callers.py`
* `scripts/audit/canonical_vs_legacy_parity.py`
* `database/instruments_repo.py` — IdentifierKind +
  identifier_resolve_one_instrument
* `services/instrument_resolution.py`
* `tests/audit/test_symtoken_callers_zero_leaks.py`
* `tests/resolver/test_resolver_no_legacy_for_non_india.py`
* `tests/instruments_repo/test_identifier_lookup.py`
* `docs/refactor/symtoken_callers.md`
* `docs/refactor/canonical_legacy_parity_report.md`
* ADR 0005, ADR 0008, ADR 0017, ADR 0018
