# Bowaka Strategy — Runbook

OpenAlgo `/python` strategy that consumes the Bowaka prefilter (`bowaka_prefilter.py`) and trades through Alpaca via OpenAlgo's promoted `/api/v2` lane.

## Operator quick-start

1. **Set OpenAlgo `.env` flag**: `API_V2_ALPACA=1`. (This prompt does NOT touch `.env` — it's operator action. Without the flag, the v2 dispatcher returns `503 promoted_lane_required` and the strategy halts the entry pass.)
2. **Run Alpaca instrument sync**: `venues_upsert("XNAS", ...)` and `broker_map_upsert_many(...)` populated for every ticker the prefilter can produce.
3. **Export env vars** before launching:
   - `OPENALGO_API_KEY=<your key>`
   - `HOST_SERVER=<openalgo url>` (default `http://127.0.0.1:5000`)
   - `OPENALGO_STRATEGY_EXCHANGE=CRYPTO` (workaround so `/python`'s Indian holiday gate doesn't fire — the strategy enforces its own NYSE session check).
4. **Launch**:
   ```
   python strategies/scripts/bowaka_strategy.py --config strategies/scripts/bowaka_strategy.yaml
   ```
5. **Stopping**: `SIGTERM` / `SIGINT` for clean shutdown. Or one of the kill flags below for graded shutdowns.


## Phase 6 — Bankroll envelope + equal-slice sizing

Phase 6 introduces a strategy-specific bankroll that's distinct from the
broker account equity. All sizing decisions operate against the bankroll;
profits compound it up to a configurable cap and losses (clamped at $0)
shrink it. The state persists across restarts via `state.json`.

### Cfg shape (`cfg.bankroll`)

```yaml
bankroll:
  initial:
    pct_of_cash: null       # exactly one must be set
    fixed_dollars: 90000
  cap_dollars: 300000       # null = unbounded; profits above cap forfeit
  reset_token: ""           # change this string to force a re-seed
  daily_allocation:
    enabled: true
    days: null              # null = use cfg.exits.max_hold_days
```

- **Seed**: at first launch (or when `reset_token` changes) the strategy seeds
  `state.bankroll.current_dollars` from `initial.fixed_dollars` or
  `initial.pct_of_cash × /api/v2/balances.cash`. Misconfigured cfg
  (`pct_of_cash` AND `fixed_dollars` both set, or both null, or non-positive)
  raises `BankrollConfigError` at startup → exit code 5.
- **Growth / drawdown**: `apply_realized_pnl_to_bankroll` runs inside
  `close_position` after every realized closure. Cap clamps the upside;
  the floor clamps at $0 on the downside. `high_water_mark` is monotonic.
- **Reset**: change `reset_token` in YAML to any new string and restart.
  The strategy stores `state.bankroll.last_reset_token` and only re-seeds
  when the YAML's token differs.
- **Daily allocation**: when enabled, the per-trade sizing basis becomes
  `bankroll / max_hold_days` (so the strategy never runs out of fresh
  capital while older vintages are still carried). The gross-exposure
  cap still uses the FULL bankroll so cumulative exposure is bounded by
  `max_gross_exposure_pct × bankroll`, not by the daily slice.
- **Disable**: omit the whole `bankroll` block — sizing reverts to broker
  equity (pre-Phase-6 behavior).

### Equal-slice sizing (`cfg.sizing`)

```yaml
sizing:
  per_trade_pct: 0.10       # used only when equal_slice_per_position is false
  max_concurrent_positions: 18
  equal_slice_per_position: true
  equal_slice_bankroll_fraction: null   # null = auto-couple to gross-cap
```

When `equal_slice_per_position` is true, every trade is sized to
`fraction × bankroll / max_concurrent_positions`, ignoring `per_trade_pct`.
The fraction resolves in this order:

1. Explicit `equal_slice_bankroll_fraction` if set in (0, 1].
2. **Auto-couple** to `risk.max_gross_exposure_pct` (so `max_concurrent × per_trade`
   lands exactly on the gross cap — no idle slots, no last-trade-blocked surprises).
3. `1.0` (full bankroll) when both are unset.

Concrete: bankroll=$90k, max_gross=0.80, max_concurrent=18 →
per_trade = `0.80 × $90,000 / 18` = **$4,000**. As the bankroll
compounds, per-trade size scales proportionally (each $1 of bankroll
moves per_trade by `fraction / max_concurrent` ≈ 4.4¢ in this config).

### State schema additions

| Field | Purpose |
| --- | --- |
| `state.bankroll.current_dollars` | The live envelope. Read by sizing; written by closures. |
| `state.bankroll.high_water_mark` | Monotonic max. Postmortem-only. |
| `state.bankroll.initialized_at` | ISO timestamp of the most recent seed. |
| `state.bankroll.initial_source` | Human-readable record of how the seed was computed (e.g. `pct_of_cash=0.10 × cash=99561.86 (initial clamped to cap=10000)`). |
| `state.bankroll.last_reset_token` | The cfg token in force at the last (re)seed. Reseed triggers when YAML differs. |

### Operator runbook

- **Seed at strategy start**: set `fixed_dollars` or `pct_of_cash` and an empty
  `reset_token`. Launch. The log line `bankroll initialized: $X.XX (source: ...)`
  confirms the seed.
- **Drawdown recovery**: nothing to do; per-trade size shrinks with the
  bankroll automatically.
- **Force a reset**: change `reset_token` to any new string (suggested:
  ISO date + reason, e.g. `"2026-05-11-seed-90k"`). Restart. The strategy
  logs the re-seed.
- **Disable mid-flight**: delete the `bankroll` block from YAML. After
  restart, sizing falls back to broker equity. State's `bankroll` dict
  is ignored but preserved (re-enable any time).

## Phase 5 — Post-closure rescreen + per-trigger telemetry

Carryover positions exiting in the morning would otherwise leave the
strategy idle for the rest of the day even with full headroom on the
gross-exposure cap. Phase 5 re-runs the entry pass after any intraday
closure so freed capacity gets redeployed.

### Cfg shape (`cfg.entry.post_closure_rescreen` + `cfg.risk.max_total_entries_per_day`)

```yaml
risk:
  max_total_entries_per_day: 10     # hard daily entry cap (open-tick + rescreen)

entry:
  intraday_confirmation:
    enabled: true                    # gate is now ON by default with rescreen
    window_minutes: 5
    max_spread_pct: 0.02
    max_quote_age_seconds: 60
    price_band:
      max_pct_above_close: 0.30      # open-tick band
      min_pct_below_close: -0.15
    post_closure_price_band:
      max_pct_above_close: 0.10      # tighter band for post-closure entries
      min_pct_below_close: -0.08
  post_closure_rescreen:
    enabled: true
    last_entry_time: "14:00"         # ET cutoff for new entries
```

### Triggers

| Closure reason | Sets `rescreen_pending`? |
| --- | --- |
| `target_hit` | Yes |
| `stop_hit` | Yes |
| `time_stop` (exit role fill) | Yes |
| `signal_fade` | **No** — fires at 16:05 ET, past the entry cutoff. |
| `kill_switch_l2` / `kill_switch_l3` | No — kill switch supersedes. |
| `closed_externally` | No — surfaced during reconcile, not the active session. |

`run_time_stop_pass` also sets the flag when at least one ticker is
time-stopped that pass.

### Gates inside `run_post_closure_rescreen`

In order — earlier rejection clears `rescreen_pending` to avoid burning
the next tick:

1. `rescreen_pending == False` → no-op.
2. `cfg.entry.post_closure_rescreen.enabled == False` → clear flag.
3. Active kill switch → clear flag.
4. Past `last_entry_time` (ET, fail-closed on bad cfg) → clear flag.
5. `state.daily_entries_count >= cfg.risk.max_total_entries_per_day` → clear flag.
6. `/api/v2/balances` fetch fails → **keep** the flag (next tick retries).
7. Reload candidates (same `as_of_date` validation as the open-tick pass).
   Failure → clear flag, log loudly, operator action.
8. `select_entries` with the remaining-budget cap.
9. `filter_by_intraday_confirmation` with `band_override = post_closure_price_band`.
10. Submit OTOCO for each survivor. Per-entry counter bumps as state is updated.

### State schema additions

| Field | Purpose |
| --- | --- |
| `state.entered_today` | List of tickers submitted today, any trigger. Powers the same-day re-entry block. |
| `state.daily_entries_count` | Total entries submitted today (open-tick + rescreen). Bounds chaining. |
| `state.rescreen_pending` | Bool flag set by every intraday closure; cleared once per tick by the rescreen helper. Debounces multiple per-tick closures into a single rescreen. |
| `state.rescreens_today` | Telemetry: count of rescreen passes today. |
| `state.post_closure_entries_today` | Telemetry: count of entries submitted via the rescreen path today. |

### Per-trigger telemetry

Every position records `entry_trigger: "session_open" | "post_closure_rescreen"`
in state. That tag propagates to the `opened` and `closure` records in
`daily_summary.jsonl`. The end-of-day `session_summary` record carries a
`by_trigger` breakdown:

```json
{
  "record_type": "session_summary",
  "session_date": "2026-05-12",
  "count_opened": 9, "count_closed": 4,
  "total_realized_pnl": -1270.93,
  "by_reason": {"stop_hit": 4},
  "by_trigger": {
    "session_open": {"opened": 6, "closed": 4, "realized_pnl": -1270.93},
    "post_closure_rescreen": {"opened": 3, "closed": 0, "realized_pnl": 0.0}
  },
  "rescreens_today": 4,
  "post_closure_entries_today": 3
}
```

The trigger-segmented numbers let the operator A/B the policy after a
week of live data without re-deriving from raw jsonl.

## Phase 4 — Risk + Reconciliation

Phase 4 closes the loop:

- **Daily P&L circuit breaker**: each in-session tick fetches equity from `/api/v2/balances` and compares to the session baseline. Drop ≥ `cfg.risk.daily_loss_pct` trips `state.daily_pnl_tripped`. Trip blocks new entries; existing positions still run normal exits. Auto-resets at the next session start.
- **Halt detection**: `_is_halt_signal` recognizes Alpaca's `held` / `pending_review` statuses and reject reasons containing `halt`. Phase 4 ships the detector + tests; the runtime wiring (skip on entry, retry on exit) is gated by the same `halt_skip_today` mechanism Phase 2 added to `submit_otoco`.
- **Restart reconciliation**: on every startup, `reconcile_at_startup` fetches `/api/v2/positions` and `/api/v2/orders?status=open|all`, then:
  - Tickers in state but missing from broker → recover the real fill price from tracked child orders (target / stop / standalone exit) and write the closure record with the actual realized P&L. Falls back to a $0 `closed_externally` stub only when no tracked child fill is found. Each recovered record carries `recovered_from_child_fill: true` so analytics can filter.
  - Qty mismatch → state corrected to broker's qty (logs the correction).
  - Untracked broker positions → log warning, do NOT auto-claim (operator decides).
  - Child orders that vanished from open list → state's `child_status_at_recon` updated.
  - Pending signal-fade exits filled overnight → close via the standard path.
- **Kill switches (full implementation)**:
  - **L1** (`KILL_NEW.flag`): blocks new entries (already wired in Phase 2). Existing positions run normal exits.
  - **L2** (`KILL_SOFT.flag`): cancels OCO + market-sells every open position with `reason="kill_switch_l2"`. Idles after close (no new entries; allows L3 escalation).
  - **L3** (`KILL_HARD.flag`): cancels OCO + market-sells best effort, persists state, exits with code 99.
  - Higher level wins if multiple flags are present.
  - Time-stop and signal-fade are SUPERSEDED under L2 (positions exit via L2's path instead).
- **Daily summary log**: at session end (15:55 ET) once per day, `write_session_summary` reads today's closures from `daily_summary.jsonl` and appends a `record_type="session_summary"` record with `count_opened`, `count_closed`, `total_realized_pnl`, and exits-by-reason.

### `state.json` schema (recovery)

If `state.json` becomes corrupt or you want a clean start:
1. Stop the strategy (SIGTERM).
2. Move `state.json` aside: `mv data/state.json data/state.json.bak`.
3. Optionally inspect with `cat data/state.json.bak | python -m json.tool`.
4. Restart. Reconciliation will surface any "untracked broker position" — manually decide to flatten or hand-edit state.

### `daily_summary.jsonl` format

JSON Lines, append-only. Each line is one of:

- `record_type: "opened"` — one per parent-fill event. Carries the analytic-enrichment context the operator uses to tune gates: signal_strength, candidate_close, gap_at_open_pct, target_pct/stop_pct/target_price/stop_price, bracket_pricing_mode, equity_at_entry, notional, notional_pct_of_equity, intraday_confirmation_enabled, **entry_trigger**.
- `record_type: "closure"` — one per closed position. Fields: `ticker`, `qty`, `entry_price`, `exit_price`, `entry_timestamp`, `exit_timestamp`, `realized_pnl`, `reason`, `entry_features`, plus analytic enrichment: `signal_strength`, `candidate_close`, `target_pct/stop_pct/target_price/stop_price`, `bracket_pricing_mode`, `hold_trading_days`, `entry_to_exit_pct`, `peak_since_entry`, `trough_since_entry`, `mfe_dollar/mae_dollar/mfe_pct/mae_pct`, `link_id`, **`entry_trigger`**, and (for reconcile-recovered closures only) **`recovered_from_child_fill: true`**.
- `record_type: "session_summary"` — one per session day at 15:55 ET. Fields: `session_date`, `count_opened`, `count_closed`, `total_realized_pnl`, `by_reason`, **`by_trigger`** (Phase 5: per-trigger opened/closed/realized_pnl breakdown), **`rescreens_today`**, **`post_closure_entries_today`**.

### Test discipline

The strategy ships with 6 phase-test files (`test_bowaka_strategy.py` for skeleton, `test_bowaka_phase2.py` for entries, `_phase3.py` for exits, `_phase4.py` for risk/reconcile, `_phase5.py` for post-closure rescreen + telemetry, `_phase6.py` for bankroll envelope + equal-slice sizing). The api_v2 regression suite (`tests/api_v2/`) is the strategy's contract floor — any drift there will surface bugs in the strategy, so both must pass before deploying changes.

If a test ever fails after a refactor, fix root causes; don't paper over with mocks. The phased prompts allow up to 5 fix attempts per phase before stopping.

## Phase 3 — Exits

Phase 3 adds script-managed exits:

- **Time-stop**: every tick during session, filled positions whose entry is `cfg.exits.max_hold_days` *trading* days behind (NYSE calendar) get exited via cancel-OCO + market sell (TIF=DAY).
- **Signal-fade EOD subroutine**: at `cfg.session.signal_fade_eval_time` (16:05 ET) once per day (deduped via `state.signal_fade_evaluated_for_date`), every filled position is re-evaluated. The strategy fetches its daily bars via `POST /api/v2/bars` (~30 calendar days back), recomputes the prefilter feature math, and compares against `cfg.signal_gates`. Any failed gate triggers cancel-OCO + market sell with TIF=OPG (MOO for next session).
- **Position closure** taxonomy: `target_hit`, `stop_hit`, `time_stop`, `signal_fade`, plus `kill_switch_l2`/`kill_switch_l3` (Phase 4) and `closed_externally` (Phase 4 reconciliation).
- **Daily summary jsonl**: each closure appends a record to `cfg.paths.daily_summary_path` with realized PnL.

### Feature-math duplication

Phase 3 deliberately duplicates the prefilter's `compute_features` body inside the strategy as `compute_features_single` (one ticker at a time). The duplication is intentional:

- The prefilter is a JSON-contract producer; refactoring it to share a feature module crosses the contract boundary and risks breaking the deployed pipeline.
- A regression test (`tests/strategies/test_bowaka_phase3.py::test_signal_fade_features_match_prefilter`) feeds both implementations the same synthetic bar dataframe and asserts the produced feature dict matches within float tolerance. Any future drift breaks this test.

### Exit reasons

| Reason | Trigger | Sets `rescreen_pending`? |
| --- | --- | --- |
| `target_hit` | OCO take-profit child fills (Alpaca-side). | Yes |
| `stop_hit` | OCO stop-loss child fills (Alpaca-side). | Yes |
| `time_stop` | Position has been open `max_hold_days` trading days. Script cancels OCO + market sells (TIF=DAY). | Yes |
| `signal_fade` | EOD feature math fails any gate. Script cancels OCO + market sells (TIF=OPG / MOO for next session). | No (fires past `last_entry_time`) |
| `kill_switch_l2` | Phase 4. | No (kill supersedes) |
| `kill_switch_l3` | Phase 4. | No (kill supersedes) |
| `closed_externally` | Phase 4 reconciliation: position vanished from broker between restarts. With the Phase-4 recovery, this reason now appears with the **real** `exit_price` / `realized_pnl` when a tracked child fill is found; only the no-fill fallback writes a $0 stub. | No (offline event) |

## Phase 2 — Candidates + Entry

Phase 2 wires the entry side:

- Candidates ingestion from the prefilter's `data/in_play_candidates.json` with strict validation: `as_of_date` must be ≤ `prefilter_handshake.max_age_trading_days` *trading* days old (NYSE calendar), and `config_hash` must match `prefilter_handshake.expected_config_hash` when pinned. Three distinct exception types let the operator log specifically: `CandidatesMissing`, `CandidatesStaleError`, `CandidatesHashMismatch`.
- Equity fetch via `GET /api/v2/balances` (uses `equity` when present, falls back to `cash`).
- Position sizing: `floor(equity * per_trade_pct / close_price)` (whole shares — fractional is rejected by Alpaca for brackets).
- Gross-exposure cap: percent (`risk.max_gross_exposure_pct`) or absolute dollars (`risk.max_gross_exposure_dollars`); absolute cap takes precedence when set.
- `select_entries` walks candidates by signal_strength, applying every gate from the architecture decisions (open-position dedup, halt-skip list, daily-pnl trip, kill-switch state, per-trade dollars, gross cap, max concurrent).
- OTOCO submission via `POST /api/v2/orders/combo`. Body shape mirrors `tests/api_v2/test_orders_combo.py`: parent MARKET BUY + LIMIT take-profit + STOP stop-loss, all WHOLE-share, TIF=DAY, session=REGULAR, `link_id` = `BOWAKA-<TICKER>-<unix>`.
- Single market sell helper used by Phase 3 exits (`POST /api/v2/orders` with TIF parameter — Phase 3 passes `OPG` for MOO).
- Idempotent cancel helper (`DELETE /api/v2/orders/<id>`; treats 404 / "already canceled" / "already inactive" as success).
- Fill polling via `GET /api/v2/orders?status=all` updates state on parent fill (entry_price, qty), parent cancel/reject (drops position; partial fill preserved), and child fills (Phase 3 wires position closure).

### Prefilter handshake

| Field | Validated against |
| --- | --- |
| `as_of_date` | NYSE-trading-day distance from today must be ≤ `max_age_trading_days` (default 1). |
| `config_hash` | Equal to `prefilter_handshake.expected_config_hash` (or pin = `null` to skip). |

A drift in either field abandons the entry pass with a logged error — the strategy will not trade off a stale or off-spec candidate set.

### Entry order flow

1. First session tick of the day (`state.session_date != today`):
   - Fetch equity → snapshot baseline.
   - `reset_for_new_session(today, equity)`.
   - Load + validate candidates; sort by `signal_strength` descending.
   - Apply gates → top N selected.
   - Submit OTOCO for each. Persist state after each submission.
2. Each subsequent tick: `poll_fills` reconciles broker order state.

### Behavior on broker errors

| Response | Action |
| --- | --- |
| `200 OK` with bracket payload | Record parent + child IDs in `state.open_positions[ticker]` (`status="pending_fill"`). |
| `422 unsupported_capability` (bracket\_\*) | Log; add ticker to `halt_skip_today`; don't retry today. |
| `422` instrument-mapping error | Log; add ticker to `halt_skip_today`; operator action: run Alpaca instrument sync. |
| `503 translator_not_registered` / `promoted_lane_required_for_non_india_broker` | Log loudly; operator action: set `API_V2_ALPACA=1` in `.env`. NOT a per-ticker problem — don't add to halt list. |

## Phase 1 — Skeleton

Phase 1 ships the harness only:

- CLI bootstrap (`--config`, `--dry-run`, `--once`)
- YAML config loader and stable `config_hash` (matches the prefilter)
- File + stdout logging
- State persistence (`data/state.json`, atomic write)
- NYSE session-window check via `pandas_market_calendars`
- File-presence kill switches (`KILL_NEW.flag`, `KILL_SOFT.flag`, `KILL_HARD.flag`)
- SIGTERM / SIGINT handlers that persist state and exit cleanly
- No-op main loop

Entries, exits, risk gates, and reconciliation are added in Phases 2–4.

## Required environment variables

| Variable | Purpose |
| --- | --- |
| `OPENALGO_API_KEY` | API key the strategy uses to call `/api/v2`. Required. |
| `HOST_SERVER` | Base URL of OpenAlgo (default `http://127.0.0.1:5000`). |
| `OPENALGO_STRATEGY_EXCHANGE` | Set to `CRYPTO` so the `/python` host's Indian-holiday gate doesn't apply. The strategy enforces its own NYSE session check. |

## Required OpenAlgo configuration (operator action)

`API_V2_ALPACA=1` in OpenAlgo's `.env`. This prompt does NOT touch `.env`. Without the flag set, the strategy cannot route orders through the promoted lane and entry attempts will get `503 promoted_lane_required` from `/api/v2/orders`.

Alpaca instrument sync must also have run so canonical-symbol → `broker_map` is populated for the tradable universe (`venues_upsert("XNAS", ...)` + `broker_map_upsert_many` for each ticker the prefilter can produce).

## Launching

```
python strategies/scripts/bowaka_strategy.py --config strategies/scripts/bowaka_strategy.yaml
```

The `/python` host launches the script with `OPENALGO_STRATEGY_EXCHANGE=CRYPTO` set. Run-as-script for development is identical: just export the env vars first.

## Kill switches

Place a file in the directory configured by `paths.kill_switch_dir` (default `.`):

- `KILL_NEW.flag` → L1: no new entries, existing positions run normal exits.
- `KILL_SOFT.flag` → L2: no new entries, cancel OCO children, market-out every open position. *(Phase 4 wires the actual market-out; Phase 1 logs only.)*
- `KILL_HARD.flag` → L3: cancel + immediate market-out + persist + exit code 99. *(Phase 4 wires the cancel/market-out; Phase 1 exits 99 cleanly.)*

Highest-precedence flag wins if multiple are present (L3 > L2 > L1).

## State file

`strategies/scripts/data/state.json` is gitignored. Schema is documented inline at the top of `bowaka_strategy.py`.

Atomic write: `state.json.tmp` → fsync → rename. The orphan `.tmp` is harmless if the process crashed mid-write.

## Logs

`strategies/scripts/logs/bowaka_strategy.log` (gitignored). Stdout is captured by the `/python` host.

## Troubleshooting

- **`OPENALGO_API_KEY must be set`** — export it before launching.
- **Strategy keeps logging "outside session window"** — expected outside 09:30–15:55 ET, on weekends, and on NYSE holidays. The script intentionally does nothing in those windows.
- **Strategy exits with code 5 at startup** — bankroll cfg is malformed. The log line `bankroll cfg invalid; refusing to start: ...` names the field. Common causes: both `pct_of_cash` and `fixed_dollars` set (or both null), `cap_dollars <= 0`, `daily_allocation.days <= 0` when enabled.
- **YAML bankroll change has no effect** — the bankroll persists across restarts. Change `cfg.bankroll.reset_token` to a new string to force a re-seed, then restart.
- **Rescreen never fires after closures** — check that `cfg.entry.post_closure_rescreen.enabled` is `true`, you're inside the entry window (before `last_entry_time` ET), `state.daily_entries_count` is under `cfg.risk.max_total_entries_per_day`, and no kill switch is active. Each gate logs the rejection reason.
- **Per-trade sizes look wrong (too big / too small)** — check `state.bankroll.current_dollars`, `cfg.sizing.equal_slice_per_position`, and `cfg.sizing.equal_slice_bankroll_fraction` (or its auto-coupled value `cfg.risk.max_gross_exposure_pct`). The startup log line `Loaded N candidates ... sizing_basis=X.XX, gross_basis=Y.YY` confirms both.
