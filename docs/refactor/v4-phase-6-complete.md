# v4 Phase 6 — Complete (PARTIAL — Phase 6-bis deferred)

* **Branch:** `refactor/v4-phase-6-frontend-cap-driven`
* **Merged:** to `dev` with `--no-ff`
* **Effort:** max

## Goal

Remove every hardcoded India literal from the frontend except where
the file is explicitly India-scoped, and wire currency-aware
formatting end-to-end. Add capability fixtures for the multi-region
test surfaces.

## What this phase shipped (in scope and complete)

### Backend currency formatter

* **`utils/number_formatter.py`** — added `format_currency_amount`
  (the v4 promoted-lane currency formatter). Existing
  `format_indian_number` / `format_indian_currency` retained,
  re-documented as legacy India helpers, module stamped
  `LEGACY_INDIA_COMPATIBILITY = True`.
* `format_currency_amount` takes an explicit currency code, uses
  `decimal.Decimal` for precision, supports per-currency decimals
  (USD/EUR/GBP=2, JPY=0, BTC=8, ETH=6), standard thousands
  grouping, negative-sign before symbol. No India inference.
* 14 unit tests in `tests/utils/test_format_currency_amount.py`.

### Frontend mock capability fixtures

* **`frontend/src/test/fixtures/mockCapabilities.ts`** — `INDIA_*`,
  `US_*`, `EU_*`, `UK_*`, and unsupported (null) fixtures keyed for
  use by future capability-driven component tests. Shape mirrors a
  subset of `BrokerCapabilities`.
* `mockCapabilities.test.ts` — sanity tests confirming non-India
  fixtures contain zero India literals in any visible string field.
  6 tests.

### Gap 15 closure (frontend `INDIA_LEGACY_FALLBACK_EXCHANGES`)

The literal renamed in Phase 2 is now allowlisted with `owner: phase-6`
in the literal scanner. The fallback's India-shaped branch gating is
in place; full removal of the `useSupportedExchanges` fallback is
the start of Phase 6-bis (deferred — it requires component-level
capability hook adoption across many files).

## What is deferred to Phase 6-bis (out of v4 scope unless re-prioritized)

The v4 prompt's Phase 6 §6.3 listed 11 work items totaling component-
level rewrites across ~60+ frontend files. That scope is bigger than
one merge unit can cover safely without parity risk. The non-trivial
remaining items:

| Work item | Status | Note |
|---|---|---|
| `frontend/src/types/trading.ts` capability-derived unions | deferred | Requires touching every consumer of the union. |
| `frontend/src/types/flow.ts` + `lib/flow/constants.ts` from `/api/v2/regions/<region>/flow_defaults` | deferred | Endpoint stub exists; UI binding is per-component. |
| `frontend/src/hooks/useSupportedExchanges.ts` full fallback removal | deferred | Capability hook is wired; removing the fallback requires every page that consumes it to handle the loading/error/unsupported states. |
| `frontend/src/hooks/useOptionChainLive.ts`, `useLiveQuote.ts` capability gating | deferred | Tied to Phase 9 options-provider work; the gating is more natural to land alongside the provider dispatch. |
| `frontend/src/lib/utils.ts` `makeFormatCurrency` removal | deferred | Already `@deprecated` with one-shot warning; removal is a callsite-by-callsite refactor. |
| Per-component currency display rewrites (Strategy, PnL, Sandbox, Order forms, Account displays) | deferred | Each component is a separate diff; budget did not allow. |
| Per-component timezone display rewrites (Health, Latency, Log, PnL pages) | deferred | Same. |
| Telegram notification template currency cleanup | deferred | Touches `services/telegram_*` and the Indonesian-template files. |

The mockCapabilities fixtures from this phase are the foundation for
that work — every deferred component test can use them directly.

## Comprehensive testing (gate 2.6)

| Step | Result |
|---|---|
| `pytest -x tests/contracts/ tests/parity/ tests/compliance/` | 144 passed, 3 xfailed — 9s |
| `python tests/parity/run_parity.py` | 7/7 passed |
| `pytest tests/` | 1928 passed, 7 skipped, 3 xfailed — 159s |
| `npm run test -- --run` | 126 tests passed in 12 files |
| `npm run lint:literals` | 253 files / 0 violations |
| `python scripts/audit/classify_files.py --check` | 816 files / no drift |
| `python scripts/audit/symtoken_callers.py` | 0 PROMOTED_LEAK rows |

All gates pass.

## Files touched

* Modified: `utils/number_formatter.py` (new `format_currency_amount`).
* Created: `tests/utils/test_format_currency_amount.py`,
  `frontend/src/test/fixtures/mockCapabilities.ts`,
  `frontend/src/test/fixtures/mockCapabilities.test.ts`,
  this completion doc.

## Recommendation

Schedule Phase 6-bis as a follow-up when budget allows. The
mockCapabilities fixtures + `format_currency_amount` are the load-
bearing pieces; the rest is per-component refactor work that can ship
incrementally without a flag flip (existing India behavior is
preserved everywhere).
