# Bowaka v2 — Operator Runbook

## Startup sequence

Run in this order, every day:

1. **Universe builder** (cron @ 02:00–06:00 MT, mon-fri):
   ```
   ./strategies/scripts/run_bowaka_universe_builder.sh
   ```
   Writes `data/bowaka_v2/universe_snapshot.json` +
   `daily_feature_cache.parquet`.

2. **Intraday scanner** (cron @ 09:40 ET, mon-fri):
   ```
   ./strategies/scripts/run_bowaka_intraday_scanner.sh
   ```
   Appends events to `data/bowaka_v2/candidate_events.jsonl` while
   `09:45 <= now <= 15:30` ET. Exits itself at scanner_end.

3. **v2 strategy** (long-running watchdog):
   ```
   ./strategies/scripts/_watchdog_bowaka_strategy.sh
   ```
   Consumes candidate_events.jsonl, applies risk + execution gates,
   submits orders, manages exits.

4. **Heartbeat monitor** (cron @ every 30s, session hours):
   ```
   ./strategies/scripts/bowaka_v2_heartbeat.py --once
   ```
   Drops `KILL_NEW.flag` if scanner heartbeat stalls > 60s.

5. **Dashboard** (operator's terminal):
   ```
   python strategies/scripts/bowaka_v2_dashboard.py --once
   ```

## Shutdown sequence

In reverse:

1. Stop the strategy (the v1 instructions still apply — kill the
   watchdog tree).
2. Stop the scanner (it exits automatically at `scanner_end`, or
   write `KILL_HARD.flag` to force).
3. Universe builder doesn't need shutting down — it's nightly.

## Kill switches

Three escalating levels at the repo root:

- `KILL_NEW.flag` — block new entries; manage open positions normally.
- `KILL_SOFT.flag` — market-out all open positions; do not enter.
- `KILL_HARD.flag` — best-effort cancel all child + parent orders, exit code 99.

`bowaka_v2_heartbeat.py` writes `KILL_NEW.flag` automatically when
the scanner stops emitting for > threshold_seconds.

## Recovery: data-feed failure

1. Check `logs/bowaka_v2_strategy.log` for `data_feed_mismatch`
   rejections.
2. Verify `cfg.data.feed` matches the prefilter cache's `data_feed`.
3. If IEX is failing, switching to SIP requires only:
   ```
   data:
     feed: "sip"
     allow_non_sip_for_research_only: false
   ```
   Then rerun the universe builder + restart the scanner.

## Recovery: broker failure

1. Strategy will retry on its own (httpx with exponential backoff).
2. If broker is down for > 5 min, write `KILL_NEW.flag` to stop
   new entries while you investigate.
3. Open positions still have OCO brackets at the broker — they're
   protected without the strategy running.

## Halt handling

The v2 halt_gate refuses to enter symbols whose live status is
`halted` / `pending_review` / `luld_pause`. Rejected entries are
logged with `reason: halt_or_pending_review`. The protection
invariant continues to apply to held positions whose underlying
halts — it can submit a fallback stop, or force-flatten if the
deadline expires.

## Unprotected-position handling

`protected_position.block_entries_on_violation: true` means: if
ANY held position becomes unprotected (no OCO + no fallback stop +
deadline elapsed), the strategy stops submitting new entries until
the operator resolves it. Check
`data/bowaka_v2/protection_events.jsonl` for the offending symbol.

## Paper → live flip checklist

Before flipping `strategy.environment: live`:

1. SIP feed validated for at least 30 trading days.
2. Paper run trades reconciled vs backtester within tolerance.
3. Risk limits matched to live capital (NOT paper).
4. Operator review signed off (per handoff §8.10).
5. Live broker credentials in `OPENALGO_API_KEY` env.
6. Watchdog cron confirmed running.
7. Heartbeat monitor confirmed running.
8. Dashboard confirmed accessible.

If any item fails, stay in paper.
