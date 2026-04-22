# Canary rollout runbook — market-agnostic refactor

> **Audience:** operators ready to flip refactor flags on in production.
> **Prerequisites:** Phases 0–7 + 9 merged to `main`. `parity-baseline`
> and `parity-v2` CI jobs green on the merge commit.

This is not a rollout _plan_ — it's a checklist you run when you
choose to canary. Every flag defaults OFF; legacy Indian/Delta
behavior is the production default until the last flag in this
runbook is flipped.

## Pre-flight checklist

Run through these before flipping any flag:

- [ ] CI `parity-baseline` and `parity-v2` both green on the current
  deploy's commit SHA.
- [ ] Full `pytest tests/` run passes locally against prod DB snapshot.
- [ ] Current `symtoken` table is backed up (a plain SQL dump is enough
  — nothing writes it under the refactor's new code paths).
- [ ] You have the rollback commit SHA written down. Rollback is a
  single env-var flip + restart; no data migration needed.
- [ ] Monitoring access: the JSON error log at `log/errors.jsonl`,
  recent `instrument_sync_runs` rows, and (if you have one) a
  request-latency dashboard.

## Flag flip order

**Do not skip or reorder.** Each flag's pre-conditions rely on the
previous flag having been stable for long enough to produce usable
signal.

### 1. `INSTRUMENT_CORE_V2` — first

**What it enables:** the Phase 2b sync runner at login time. Reads
broker instruments into the new `instruments`,
`broker_instrument_map`, `instrument_sync_runs` tables in parallel
with (not instead of) the legacy `symtoken` sync.

**Side effect on prod:** an extra daemon thread per login runs the
normalized sync. Writes are confined to the five Phase 2a tables;
`symtoken` is not touched.

**Watch:**
- `log/errors.jsonl` for any `instrument sync FAIL` lines.
- `SELECT status, COUNT(*) FROM instrument_sync_runs GROUP BY status;`
  — expect mostly `success`, zero `failed`. Transient `running` rows
  older than ~15 min suggest a hung adapter; investigate.
- Login latency — the new thread is async and should not affect
  user-observed login time.

**Rollback threshold:** any `instrument sync FAIL` that does not
reproduce in staging, or login latency regression > 500ms p95.

**Rollback:** unset `INSTRUMENT_CORE_V2`, restart. Existing rows in
`instruments` / `broker_instrument_map` stay in the DB and are
simply not updated.

**Stability bar:** run for **24h** and inspect `instrument_sync_runs`
shows the expected row count per broker (one `success` per login
attempt) before moving to the next flag.

---

### 2. `RESOLVER_V2`

**What it enables:** the Phase 3a `InstrumentResolver` observability
probe inside `services.quotes_service` and `services.history_service`.
Runs the resolver alongside the legacy `get_token` path and logs
hit / miss / ambiguous / legacy-fallback outcomes.

**Side effect on prod:** an extra DB query per quote and history
request to resolve the instrument. Output `/api/v1` response is
**unchanged** — the resolver does not drive the broker call in this
phase.

**Watch:**
- `log/errors.jsonl` for `resolver_exception` entries — should be
  zero; any non-zero count indicates a resolver bug.
- DEBUG logs for `resolver_hit` count vs `resolver_miss_falling_back`
  count. A healthy ratio is > 95% hit (new instruments universe
  populated enough) after INSTRUMENT_CORE_V2 has run for 24h.
- Quote / history latency: the resolver has a 60s TTL cache; after
  warm-up the overhead per request should be ≤ 2ms p95.

**Rollback threshold:** `resolver_exception` count > 0; latency
regression > 10ms p95 on quote/history endpoints.

**Rollback:** unset `RESOLVER_V2`, restart. No state cleanup needed.

**Stability bar:** 48h of steady-state traffic with zero
`resolver_exception` entries.

---

### 3. `VENUE_SESSION_V2`

**What it enables:** `services.market_calendar_service` reads the
default venue's timezone from the Phase 2a `venues` table instead of
returning the hardcoded `"Asia/Kolkata"`. For Indian deployments the
resolved value **is** `Asia/Kolkata`, so `/api/v1/marketcalendar` is
byte-identical.

**Side effect on prod:** one extra `SELECT` per
`/api/v1/marketcalendar` request. Response shape unchanged.

**Watch:**
- Any unexpected `timezone` values in `/api/v1/marketcalendar`
  responses (for an Indian broker install it must still be
  `Asia/Kolkata`).
- `VenueSessionService` is not yet wired into the four consumers
  the playbook flagged (historify_scheduler, iv_chart_service,
  straddle_chart_service, python_strategy). Those still use
  `pytz.timezone("Asia/Kolkata")` directly. That is expected for
  this rollout; a follow-up phase wires them through.

**Rollback threshold:** any `/api/v1/marketcalendar` response with
a timezone other than `Asia/Kolkata` on an Indian deployment.

**Rollback:** unset `VENUE_SESSION_V2`, restart.

**Stability bar:** 48h.

---

### 4. `WEBSOCKET_INSTRUMENT_V2`

**What it enables:** outbound WebSocket tick / depth payloads carry
an additive `instrument_id` field when the subscription went through
`subscribe_by_instrument_ref`. Subscriptions made via the legacy
`subscribe(symbol, exchange)` path are unchanged.

**Side effect on prod:** outbound JSON payload gains one key.
Existing clients ignore unknown keys.

**Watch:**
- Any client parser that breaks on extra keys. OpenAlgo's own React
  frontend and MCP server do not; third-party subscribers are
  operator-dependent.
- Payload size growth: an extra UUID-string is ~40 bytes per tick.

**Rollback threshold:** any SDK client breakage reported within the
first hour of flag-on.

**Rollback:** unset `WEBSOCKET_INSTRUMENT_V2`, restart the Flask
app (WebSocket adapters pick up the new value on reconnect).

**Stability bar:** 24h.

---

### 5. `HISTORIFY_INSTRUMENT_ID_V2` (plus backfill)

**What it enables:** historify writes populate the `instrument_id`
column on `market_data` / `watchlist` / `data_catalog` (backfilled to
NULL previously). Dual-write only — reads continue to use the legacy
`(symbol, exchange)` keys.

**Side effect on prod:** one resolver call per historify write.
Column values stamped on new rows; COALESCE semantics preserve any
previously-set UUID on re-upsert.

**Before flipping:** run the backfill manually for each table that
needs it:

```bash
# DRY RUN first — confirms counts without writing.
uv run upgrade/backfill_historify_instrument_id.py \
    --table market_data --broker-code <your_broker>

# Once the resolved / missed counts look right:
uv run upgrade/backfill_historify_instrument_id.py \
    --table market_data --broker-code <your_broker> --commit

# Repeat for watchlist, data_catalog, etc. as desired.
```

**Watch:**
- DEBUG log `historify resolver miss` count after flipping the flag —
  every miss leaves `instrument_id` NULL on the new row.
- Historify write latency: one resolver call per write; should be
  ≤ 3ms p95 after cache warm-up.

**Rollback threshold:** miss rate > 5% sustained over an hour after
backfill (indicates an instruments-table coverage gap that should be
fixed via Phase 2b sync health rather than by flipping this flag
back off).

**Rollback:** unset `HISTORIFY_INSTRUMENT_ID_V2`, restart. The
`instrument_id` column stays populated; subsequent legacy-mode writes
leave it alone (COALESCE-preserve).

**Stability bar:** 72h. Backfill results captured in a log artifact.

---

### 6. `API_V2` — last

**What it enables:** the Phase 6 `/api/v2/*` skeleton becomes visible.
Before this flag, every `/api/v2/*` request returns 404.

**Side effect on prod:** 8 new routes live. Each either proxies to
an existing v1 service (quotes, bars, positions, balances) or reads
directly from the Phase 2a instrument universe (capabilities,
instruments/search, instruments/<id>, orders). Error envelope is
structured (`{"error": {"code", "message", "details"}}`) — distinct
from v1.

**Watch:**
- 500 responses from any `/api/v2/*` route (expect zero).
- Client adoption: monitor the access log for `/api/v2/` paths.
  If no clients exercise v2 within a week, consider whether the
  canary is complete or whether v2 needs better docs.
- `/api/v1/*` traffic should be unaffected.

**Rollback threshold:** any /api/v2 500 on an existing endpoint.

**Rollback:** unset `API_V2`, restart. v2 routes return 404 again.

**Stability bar:** 2 weeks before calling the full refactor
"production stable".

## What "done" looks like

- [ ] All six flags have been on continuously for 2 weeks.
- [ ] `parity-baseline` and `parity-v2` green on every merged PR in
  that window.
- [ ] Zero `instrument_sync_v2 FAIL` entries in `log/errors.jsonl`
  for the 2-week window.
- [ ] Zero `resolver_exception` entries.
- [ ] `legacy_fallback_used=true` ratio either stays flat or trends
  down (new instruments coverage growing, not shrinking).
- [ ] No user-reported regression tied to the refactor in the issue
  tracker for the 2-week window.

Once those boxes are checked, the `docs/refactor/deprecation-schedule.md`
timeline unlocks its first milestone.

## Observability coverage

The refactor emits structured log fields from these code paths. Grep
them to confirm presence after a flag flip.

| Field | Emitted from | Code location |
|---|---|---|
| `broker_code` | sync runner start/end/fail | `services/instrument_sync_service.py` |
| `sync_id` | sync runner lifecycle | `services/instrument_sync_service.py` |
| `sync_version` | sync runner lifecycle | `services/instrument_sync_service.py` |
| `instrument_count` | sync runner success | `services/instrument_sync_service.py` |
| `duration_ms` | sync runner success/fail | `services/instrument_sync_service.py` |
| `status` | sync runner success/fail | `services/instrument_sync_service.py` |
| `venue_code` | sync runner per chunk | `services/instrument_sync_service.py` |
| `instrument_id` | resolver success | `services/quotes_service.py`, `services/history_service.py`, `services/historify_service.py` |
| `legacy_fallback` | resolver success | `services/quotes_service.py`, `services/history_service.py`, `services/historify_service.py` |
| `identifier_type` / `identifier_value` | resolver external-id path | `services/instrument_resolver.py` (ResolverMiss messages) |
| `capability` | capability-gate block | `utils/capability_guards.py` |
| `timezone_name` | venue session windows | `services/venue_session_service.py:SessionWindow.venue_timezone_name` |

Two structured log fields named in the playbook's review §9.1 are not
yet emitted:

- `market_family` — available on `venue.market_family` but not yet in
  the sync runner's log line.
- `resolver_path` — the resolver doesn't currently emit its branch
  choice (`by_id` vs `by_venue_symbol` vs `by_external`) at INFO.

Those are both small adds and are listed in
`docs/refactor/deprecation-schedule.md` as post-Phase-9 polish, not
blockers for flag rollout.
