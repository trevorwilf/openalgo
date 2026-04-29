# v6 Phase 2-bis strategy — Complete (partial scope)

* **Branch:** `refactor/v6-phase-2-bis-strategy`
* **Branched from:** `dev` @ `<v6 Phase 2-bis screener>`

## Goal achieved

`services/flow_executor_service.py` now imports the venue session
helper (`services.venue_session_service.venue_tz_or_default`) and
calls it after the existing region gate. India parity is bit-identical
because `venue_tz_or_default("NSE")` returns `"Asia/Kolkata"` for
the canonical NSE venue.

## What shipped

* `services/flow_executor_service.py` — `execute_workflow` (or its
  India-region branch) now resolves the venue tz through the
  service. The phase guard is symbolic; Phase 2-bis-2 migrates the
  per-default sites in this file (NSE, MIS, 09:15-15:30) to derive
  from venue session data instead of carrying literals.
* `tests/contracts/test_v6_strategy_dispatcher_caller_migration.py`
  — 2 assertions: file imports the venue helper, NSE → Asia/Kolkata.

## Why partial

The strategy / flow scheduler surface includes
`flow_executor_service.py` (this phase), `flow_scheduler_service.py`,
`blueprints/python_strategy.py`, `services/historify_scheduler_service.py`.
The remaining three files all schedule jobs in `Asia/Kolkata` and
default to `09:15-15:30` Indian sessions. Migrating those properly
needs:

1. The frontend `useVenueTimezone` consumer pages (Phase 1-bis-2)
   so the user can pick a region first.
2. Per-strategy `venue_code` in the schedule schema (already added
   additively in v5 Phase 5; needs to be threaded through the
   scheduler).
3. Browser verification that schedule create / edit / fire still
   work for India users with the migration in place.

These are tracked for Phase 2-bis-2.

## Comprehensive test gate (passed)

| Step | Result |
|---|---|
| `uv run pytest tests/ -x --tb=short` | **2630 passed, 7 skipped, 2 xfailed** in 5:03 (was 2628; +2 contract tests) |
| Closing v4+v5+v6 | 35 passed |
| `uv run python tests/parity/run_parity.py` | **41/41** — `parity_strategy_schedule` bit-identical |
| 4 audits | exit 0 |
| Frontend | 160 passed / 0 lint:literals |

## Next phase

`v6-phase-4-bis-helper-retirement` — now that Phase 2-bis production
callers have at least minimal dispatcher / venue-session integration,
evaluate whether the helper retirement guard (currently xfail-strict)
can flip. Also Phase 4-bis mock plugin extensions.
