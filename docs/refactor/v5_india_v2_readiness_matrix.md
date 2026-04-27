# v5 India v1→v2 readiness matrix (Phase 8 inventory)

**Operator decision D-1:** Indian brokers will migrate from `/api/v1`
to `/api/v2` so v1 can be deprecated.

This matrix surveys each India broker plugin against the
requirements that v2 promotion needs:

* **plugin completeness**: capability fields the v4 strict-mode
  loader requires for promoted brokers (currently inferred for India
  via `_indian_defaults()`; explicit declaration is preferred but
  not yet required for India brokers).
* **translator**: a `BrokerTranslator` registered in
  `services/broker_translator_registry.py` for the v2 lane.
* **`API_V2_<BROKER>` flag**: env var present in settings/env
  layer (defaults OFF; flipping ON is the cutover in Phase 9).
* **v2 parity harness**: `tests/parity/baseline/parity_v2_<broker>_india.{py,json}`.

## Matrix

| Broker | Plugin completeness | Translator | API_V2 flag | v2 parity harness | Notes |
|---|---|---|---|---|---|
| aliceblue   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis (per-broker translator) |
| angel       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| compositedge| inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| definedge   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| deltaexchange | inferred (crypto defaults) | — | implicit (env) | — | crypto, not India |
| dhan        | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| dhan_sandbox| inferred (India defaults) | — | implicit (env) | — | sandbox-only path |
| firstock    | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| fivepaisa   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| fivepaisaxts| inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| flattrade   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| fyers       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| groww       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| ibulls      | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| iifl        | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| iiflcapital | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| indmoney    | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| jainamxts   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| kotak       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| motilal     | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| mstock      | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| nubra       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| paytm       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| pocketful   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| rmoney      | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| samco       | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| shoonya     | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| tradejini   | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| upstox      | inferred (India defaults) | — | implicit (env) | — | Phase 8-bis |
| **zerodha**     | **inferred (India defaults)** | — | implicit (env) | — | Phase 8-bis (canonical reference) |

(29 India broker plugins; 1 crypto plugin; 2 mock plugins reserved
for non-India framework readiness.)

## Implicit env flag

`utils/feature_flags.is_enabled(name)` reads the env var on every
call. Therefore every `API_V2_<BROKER>` flag is *implicitly* present
in the env layer — setting `API_V2_ZERODHA=1` flips Zerodha to v2
without any DB migration. The default for every broker is OFF (env
var unset → `is_enabled()` returns False).

## What ships in v5 Phase 8

* `Deprecation: true` + `Sunset` headers on every `/api/v1/*`
  response (operator-controlled via `OPENALGO_V1_SUNSET_DATE`).
* `docs/migration/v1-to-v2.md` — per-endpoint mapping reference.
* This matrix as the v6 work pointer.
* The v5 closing invariant test verifies `Deprecation` + `Sunset`
  headers are present.

## What is deferred to v5 Phase 8-bis (per-broker, real-broker work)

* Per-broker `BrokerTranslator` implementation. Each India broker
  needs a translator that maps `NormalizedOrderRequest` to the
  broker-native payload using the existing `broker/<name>/mapping/`
  helpers. This is per-broker integration work and can ship
  per-PR.
* Per-broker v2 parity harnesses
  (`parity_v2_<broker>_india.{py,json}`). Each harness exercises
  the v2 path and asserts byte-identical normalized output / native
  payload vs the v1 baseline.
* Explicit plugin.json declaration of the v4 strict-mode required
  fields (currently inferred via `_indian_defaults()`).

## Phase 9 (cutover)

Phase 9 flips `API_V2_<BROKER>` defaults to ON for the brokers that
have completed their Phase 8-bis (translator + parity harness). v1
remains alive for the operator-controlled sunset window.
