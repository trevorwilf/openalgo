# Incident 2026-05-15 — ASPI duplicate time-stop exit

## Summary

On 2026-05-15 at 07:45 MT (live), the ASPI position fired
`trigger_time_stop` twice for the same `time_stop` reason on the
same day. The first exit market-sold the position cleanly; the
second created an unintended SHORT. An operator manually flattened
the short ~30 minutes later (linked manual_intervention event).
The double-fire was triggered by a parent FILL row lingering in the
broker's `/orders?status=all` window: the legacy `_build_order_index`
indexed the parent_order_id even after the position transitioned to
`filled`, so `poll_fills` re-entered the parent-fill branch on each
poll, repeatedly resetting `peak_since_entry` and `trough_since_entry`
to `entry_price` (corrupting MFE/MAE) and re-emitting `entry_fill`
events. The dedup guard on `trigger_time_stop` (status="exit_pending"
reservation) caught one re-fire but the second tick raced ahead of
the persist.

## Timeline

* 09:30 ET — Parent BUY filled at 5.80 for 643 shares. Position
  reaches `status="filled"`.
* 09:31 ET — Parent row still listed as FILLED in
  `/orders?status=all`. poll_fills re-processed the row and reset
  peak/trough to entry_price.
* 13:30 ET — Max-hold time reached; `trigger_time_stop` fired.
* 13:30:05 ET — Status flipped to `exit_pending` and persisted.
* 13:30:06 ET — A second `trigger_time_stop` raced through before
  the persist completed (separate tick); the second submit landed.
* 13:32 ET — Both market-sells filled; one closed the long, the
  second opened a short.
* 14:00 ET — Operator manual-bought 643 shares to flatten. Realized
  P&L impact: −$19.29.

## Root cause

1. `_build_order_index` indexed `parent_order_id` regardless of
   status, allowing the broker's lingering FILLED row to re-enter
   the parent-fill branch on every poll.
2. The `exit_pending` status-flip dedup catches in-process double-
   fires but is not atomic across tick boundaries with a slow
   persist.

## Remediation

* Phase 3 (2026-05-16): `_build_order_index` only indexes
  `parent_order_id` for pre-fill positions. `_handle_parent_fill`
  is single-shot per position; subsequent calls are no-ops and a
  `duplicate_parent_fill_suppressed` event is emitted.
  `_initialize_peak_trough_once` ensures MFE/MAE state cannot be
  reset.
* Phase 3 (2026-05-16): `trigger_time_stop` computes an
  `exit_idempotency_key = {link_id}|exit|{reason}|{entry_date}` and
  scans the canonical ledger for a matching `exit_submitted` /
  `replacement_exit_accepted` / `exit_order_accepted` event before
  submitting. Even a fast race that bypasses the status guard now
  produces at most one market-sell.

The fix shipped with the 2026-05-16 audit-remediation merges on
`dev`. ASPI-shaped replay tests in
`tests/strategies/test_bowaka_idempotency_mfe_mae.py` pin the new
behavior.
