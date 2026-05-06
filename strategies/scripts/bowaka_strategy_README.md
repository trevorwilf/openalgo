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


## Phase 4 — Risk + Reconciliation (this commit)

Phase 4 closes the loop:

- **Daily P&L circuit breaker**: each in-session tick fetches equity from `/api/v2/balances` and compares to the session baseline. Drop ≥ `cfg.risk.daily_loss_pct` trips `state.daily_pnl_tripped`. Trip blocks new entries; existing positions still run normal exits. Auto-resets at the next session start.
- **Halt detection**: `_is_halt_signal` recognizes Alpaca's `held` / `pending_review` statuses and reject reasons containing `halt`. Phase 4 ships the detector + tests; the runtime wiring (skip on entry, retry on exit) is gated by the same `halt_skip_today` mechanism Phase 2 added to `submit_otoco`.
- **Restart reconciliation**: on every startup, `reconcile_at_startup` fetches `/api/v2/positions` and `/api/v2/orders?status=open|all`, then:
  - Tickers in state but missing from broker → synthetic `closed_externally` closure record + drop from state.
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

- `record_type: "closure"` — one per closed position. Fields: `ticker`, `qty`, `entry_price`, `exit_price`, `entry_timestamp`, `exit_timestamp`, `realized_pnl`, `reason`, `entry_features`.
- `record_type: "session_summary"` — one per session day at 15:55 ET. Fields: `session_date`, `count_opened`, `count_closed`, `total_realized_pnl`, `by_reason`.

### Test discipline

The strategy ships with 4 phase-test files (`test_bowaka_strategy.py` for skeleton, `test_bowaka_phase2.py` / `_phase3.py` / `_phase4.py` for the rest). The api_v2 regression suite (`tests/api_v2/`) is the strategy's contract floor — any drift there will surface bugs in the strategy, so both must pass before deploying changes.

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

| Reason | Trigger |
| --- | --- |
| `target_hit` | OCO take-profit child fills (Alpaca-side). |
| `stop_hit` | OCO stop-loss child fills (Alpaca-side). |
| `time_stop` | Position has been open `max_hold_days` trading days. Script cancels OCO + market sells (TIF=DAY). |
| `signal_fade` | EOD feature math fails any gate. Script cancels OCO + market sells (TIF=OPG / MOO for next session). |
| `kill_switch_l2` | Phase 4. |
| `kill_switch_l3` | Phase 4. |
| `closed_externally` | Phase 4 reconciliation: position vanished from broker between restarts. |

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

The Phase 2 README update will document candidate ingestion, the prefilter handshake (`config_hash`, `as_of_date`), and entry behavior.
