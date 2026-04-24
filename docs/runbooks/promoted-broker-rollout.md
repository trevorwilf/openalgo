# Runbook — Promoted broker rollout and rollback

This runbook covers the per-broker promotion of `/api/v2` on OpenAlgo.
It is the operational companion to
[ADR 0005 — two lanes: legacy and promoted](../adr/0005-two-lanes-legacy-and-promoted.md).

## TL;DR

- **Promote a broker:** set `API_V2_<BROKER_CODE_UPPER>=1` in the
  environment and restart.
- **Roll a broker back:** set the same flag to `0` or unset it, and
  restart. No code revert required.
- **Don't force-promote without a rule matrix.** The broker's rule
  seed must run at startup before the first promoted order; if the
  rule table is empty for the broker, every promoted order returns
  422 `no_rule_matches`.

## 1. Enabling the flag

1. Edit `.env` on the server:
   ```bash
   API_V2_ALPACA=1
   ```
2. Restart the OpenAlgo service:
   ```bash
   sudo systemctl restart openalgo    # or your equivalent
   ```
3. Tail the logs and confirm:
   - `broker Alpaca capabilities loaded`
   - `broker_code=alpaca` appears in `/api/v2/orders` log lines with
     `legacy_fallback=False`.

## 2. Metrics to watch in the first hour

Scrape endpoint is defined by your Prometheus setup (OpenAlgo uses
the standard `prometheus_client` registry when installed — else all
metrics emit as debug logs).

### Should increment on promoted traffic

- `rule_rejections_total{broker="alpaca", code="*"}` — expected non-
  zero for bad client input.
- `instrument_sync_lag_seconds{broker="alpaca"}` — resets to 0 after
  every successful sync run.

### Must stay at zero

- `promoted_legacy_fallback_total{broker="alpaca"}` — a nonzero value
  means an order for `alpaca` fell through to the legacy India
  translator. This is a hard alert.
- `get_token_forbidden_calls_total{broker="alpaca"}` — any nonzero
  value is a lane-isolation breach, escalate immediately.

### Baselines

- `/api/v2/orders` p99 latency < 600 ms for paper sandbox at rest;
  < 900 ms under retail-level burst (no strict SLO — dashboards
  over-trigger on sub-minute windows).
- Error rate ≤ 1 % across all response codes including rule rejections.

## 3. Rolling a broker back

1. Set the flag to `0` (or remove the line) in `.env`:
   ```bash
   API_V2_ALPACA=0
   ```
2. Restart the service.
3. Confirm that `/api/v2/orders` for this broker starts returning
   legacy-shape responses again. The Indian translator is not
   appropriate for Alpaca — expect structured 422s from
   `UnsupportedCapability` rather than successful orders. This is
   **not** a bug; it is the correct behavior for a non-Indian broker
   on the legacy lane. Document in the incident ticket.
4. Open an incident ticket if a promoted broker needed emergency
   rollback. The fix is code-level and must not silently rely on the
   flag staying off.

## 4. Escalation matrix

| Signal | Action |
|---|---|
| `promoted_legacy_fallback_total` incrementing for any broker whose flag is on | Page on-call. Check translator/adapter registration at startup. |
| `get_token_forbidden_calls_total` nonzero | Page on-call. Lane-isolation breach — `tests/contracts/test_lane_isolation.py` should have caught it; a PR bypass is suspected. |
| `rule_rejections_total` spiking | Look at the `code` label. `no_rule_matches` suggests a missing rule seed at startup; `session_closed` during market hours suggests an incorrect override. |
| `instrument_sync_lag_seconds` stuck > 86400 | Sync stalled. Check broker auth and DB connectivity; manual re-run of `broker.<name>.sync.instrument_sync.sync_instruments()`. |

## 5. Known-good artifacts

- Alpaca paper sandbox: `https://paper-api.alpaca.markets`
- Data host: `https://data.alpaca.markets`
- Alpaca rule seed: `broker/alpaca/sync/seed_rules.py::seed_alpaca_rules`

## 6. Pre-flight checklist for promoting a new broker

- [ ] `broker/<code>/plugin.json` declares non-`india` `supported_regions`.
- [ ] `broker/<code>/PROMOTED` sentinel exists.
- [ ] `broker/<code>/sync/seed_rules.py::seed_<code>_rules()` called
      at startup (hook in `app.py setup_environment`).
- [ ] `broker/<code>/sync/instrument_sync.sync_instruments()` runs
      before first promoted order.
- [ ] `BrokerOrderTranslator` registered at startup.
- [ ] `BrokerQuoteAdapter` and `BrokerBarAdapter` registered at
      startup.
- [ ] `tests/contracts/test_lane_isolation.py` green against the
      broker directory.
- [ ] Flag `API_V2_<BROKER>=1` in `.env`; restart.
