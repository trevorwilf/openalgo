# ADR 0030 — Promoted-request observability labels (v5 Phase 1)

* **Status:** Accepted (v5 Phase 1)
* **Related:** ADR 0029 (structured market-context errors); CLAUDE.md
  "Promoted lane" section.

## Context

Two independent expert reviews flagged the same gap: there is no
single observability schema for promoted-lane requests. Each route
emits its own ad-hoc log lines, none of them include the dispatch
decision (which provider/translator/region was used), and none of
them are guaranteed to include a request id.

Without that schema:

* Operators cannot ask "how many v2 requests fell through to the
  legacy lane today" — there is no `legacy_lane=true` boolean.
* Operators cannot ask "which broker plugins missed which
  capability dimension" — there is no `capability_source` label.
* Future metrics work (Prometheus / OpenTelemetry, deferred to v6)
  has no stable label set to start from.

## Decision

Define the canonical promoted-request label set and emit it from a
single helper, `utils.observability.log_promoted_request`. v6 may
upgrade the transport (metrics backend); v5 only ships the
structured-log line.

### Label set

| Key | Source |
|---|---|
| `region_code` | `feature_gate_service.active_region_code()` |
| `broker_code` | active broker session |
| `venue_code` | request body / instrument metadata |
| `instrument_id` | canonical identity (UUID or MIC+symbol) |
| `currency` | account context > venue base_currency > instrument |
| `provider_code` | dispatcher (sandbox/options/screener) |
| `capability_source` | one of `region`, `broker`, `account`, `provider` |
| `legacy_lane` | bool — `true` only on v1 requests |
| `route` | `"v1"` or `"v2"` |
| `request_id` | best-effort framework-supplied id |

The full schema lives at
`docs/observability/promoted_request_labels.md`.

### Emission contract

* Promoted (v2) routes call `log_promoted_request(ctx, event=...)`
  exactly once per request, after the dispatch decision is made and
  before the broker network call. Errors raised before that point
  are logged via the standard error handler.
* Legacy (v1) routes do **not** call this helper. The contract test
  enforces the boundary.

### Stability

Adding a new key requires a new ADR. Renaming or removing a key
requires a major version bump.

## Consequences

* All promoted requests share one log schema. Downstream parsers
  (log shippers, future metrics exporter) can consume it.
* `legacy_lane` makes "fell through to legacy" alertable.
* No metrics backend introduced. Deferred to v6 explicitly.

## Implementation notes

* `utils/observability.py` is the single emission site.
* `tests/contracts/test_v5_observability_labels_complete.py` asserts
  the helper produces every required label and rejects incomplete
  contexts.
* The helper's `legacy_lane=True` + `route="v2"` combination logs a
  warning — it indicates a dispatch bug.

## Related

* ADR 0029 — structured market-context errors.
* `utils/logging.py` — base logger / JSON error formatter.
* `utils/traffic_logger.py` — pre-existing per-request traffic log;
  unaffected.
