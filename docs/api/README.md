# OpenAlgo API Documentation

Welcome to the OpenAlgo REST API Documentation. The REST surface is
split into two operator-controlled lanes per
[ADR 0005](../adr/0005-two-lanes-legacy-and-promoted.md).

## Two lanes

| Lane | Status | Use when |
|------|--------|----------|
| **[`/api/v1` — Legacy India lane](v1/README.md)** | Deprecated; sunset machinery in Phase 9. India-only by design. Mounted only when the India region plugin is loaded. Every response carries `Deprecation: true` + `Sunset:` headers. | You're integrating with one of the 30 supported India brokers and need bit-identical legacy behavior. |
| **[`/api/v2` — Region-neutral lane](v2/README.md)** | Promoted lane. Stable region-agnostic DTOs sourced from `domain/`. Per-broker opt-in via `API_V2_<BROKER>=1`. India broker bit-identical with v1 (Phase 6 ALL_GREEN verified — see [`docs/refactor/v6-translator-parity-status.md`](../refactor/v6-translator-parity-status.md)). | You're integrating with a non-India broker, OR you've flipped your India broker's `API_V2_<BROKER>` flag on. |

> **C-P2-027 region note** — examples in v1 docs use India-specific
> values (`NIFTY`, `NSE`, `NFO`, `MIS`, `CNC`, `NRML`, `INR`, `₹`,
> IST timestamps, 09:15-15:30 sessions). Replace with your region's
> equivalents when targeting a non-India broker. See
> [`docs/refactor/multi_region_broker_compatibility_matrix.md`](../refactor/multi_region_broker_compatibility_matrix.md)
> for per-region symbology, and
> [`docs/refactor/future-broker-onboarding-checklist.md`](../refactor/future-broker-onboarding-checklist.md)
> for the contract a non-India broker plugin satisfies.

## Choosing a lane

* New integrations targeting an India broker today: start with
  [`v1`](v1/README.md). Plan to migrate to v2 once
  `API_V2_<YOUR_BROKER>=1` is rolled out by your operator.
* New integrations targeting any non-India broker: only
  [`v2`](v2/README.md) is available.
* Existing integrations: keep using [`v1`](v1/README.md). Watch for
  `Deprecation: true` and `Sunset:` headers — your operator may have
  set `OPENALGO_V1_SUNSET_DATE` for a hard cutover. Until then v1 is
  fully supported.

## SDK Support

OpenAlgo provides official SDKs for popular programming languages:

- **Python**: `pip install openalgo`
- **Node.js**: Coming soon
- **Java**: Coming soon

## Support

- Documentation: https://docs.openalgo.in
- GitHub: https://github.com/marketcalls/openalgo
- Discord: https://www.openalgo.in/discord
