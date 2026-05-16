# Incident 2026-05-15 — signal_fade OPG rejections

## Summary

At 16:05 ET on 2026-05-15, four open positions (ASPN, ONDS, PCT, QS)
were due to receive a signal-fade MARKET SELL with `time_in_force=OPG`
under the legacy code path. The broker rejected every submission
because `MARKET + OPG` is not a valid order_type/time_in_force pair
(OPG is reserved for `market_on_open` / `limit_on_open`). The positions
remained open through the close. Compounding the problem, their stored
`protection_status` was `oco_attached` with empty `child_order_ids`,
which the legacy `has_confirmed_protection(pos)` accepted at face
value — so the protection enforcer never tried to repair them.

## Timeline

* 09:30 ET — Positions ASPN, ONDS, PCT, QS opened from the prefilter
  slate. The OCO submits succeeded at the broker initially, but the
  child IDs were not persisted (separate bug; closed in Phase 2).
* 12:00 ET — A broker reconnect cleared the open-order state at the
  broker; the strategy's stored `oco_attached` string still made
  `has_confirmed_protection` return True, so no rebracket fired.
* 16:05 ET — `run_signal_fade_pass` fired on rvol-failed positions
  and called `trigger_time_stop(..., time_in_force="OPG")`. Every
  submit returned HTTP 4xx; the strategy reverted each position to
  `filled` but did not re-attempt with a valid TIF.
* 16:30 ET — Operator noticed the unprotected positions and decided
  to hold overnight (Phase 2 startup-repair would have closed them
  the next morning).

## Root cause

Two bugs working together:

1. `submit_market_sell` accepted any `time_in_force` value without
   validation. The legacy `signal_fade` design passed `"OPG"` to get
   MOO behavior, but `MARKET + OPG` was never a valid pair.
2. `has_confirmed_protection(pos)` trusted the stored
   `protection_status` string. Four positions with stale
   `oco_attached` + empty child IDs slipped past the enforcer
   indefinitely.

## Remediation

* Phase 2 (2026-05-16): `derive_protection_state(pos, broker_orders)`
  computes protection from live broker order rows. Stored strings
  are never trusted on their face.
* Phase 4 (2026-05-16): `VALID_EXIT_COMBINATIONS` allow-list +
  `_validate_exit_combination` guard. `submit_market_sell` rejects
  MARKET+OPG before any HTTP I/O. signal_fade redesigned to use a
  marketable-limit DAY SELL via `replace_protection_with_exit`.
* `trigger_time_stop` now asserts `time_in_force in {"DAY", "GTC"}`.

Both fixes ship in the 2026-05-16 audit-remediation merges on `dev`.
