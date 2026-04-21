# Inventory 06 — Frontend capability fallbacks and "fail-open" defaults

## Summary

The frontend's capability model (`frontend/src/stores/brokerStore.ts`)
silently fails: if `GET /api/broker/capabilities` does not respond,
`capabilities` stays `null` and pages "fall back to showing all
exchanges". `useSupportedExchanges.ts:26` hardcodes the exchange list
`["NSE","BSE","NFO","BFO","CDS","MCX","CRYPTO"]` as that fallback. The
currency formatter (`frontend/src/lib/utils.ts:32`) is a **two-branch
hardcoded switch**: `deltaexchange → USD`, everything else → `INR (₹)`.

Phase 5 flips these to fail-closed and capability-driven.

## Raw citations

```
# Store: fail-open on missing capabilities
frontend/src/stores/brokerStore.ts:1-40
  capabilities is nullable; fetchCapabilities catches all errors and
  logs nothing; line 34-36:
    } catch {
      // Silently fail — capabilities will be null, pages fall back to showing all exchanges
    }

# Hardcoded exchange fallback list
frontend/src/hooks/useSupportedExchanges.ts:12-23   (derivative index/F&O hints per exchange)
frontend/src/hooks/useSupportedExchanges.ts:26
  const FALLBACK_EXCHANGES = ['NSE','BSE','NFO','BFO','CDS','MCX','CRYPTO']
frontend/src/hooks/useSupportedExchanges.ts:44
  // Use fallback exchanges when capabilities haven't loaded yet (backward compatible)
frontend/src/hooks/useSupportedExchanges.ts:46,70-73
  const isCrypto = capabilities?.broker_type === 'crypto'
  const defaultExchange = tradingExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NSE')
  const defaultFnoExchange = fnoExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NFO')

# Hardcoded currency formatter
frontend/src/lib/utils.ts:27-42
  /**
   * Returns a currency formatter bound to the active broker.
   * - deltaexchange → USD ($)
   * - all other brokers  → INR (₹)
   */
  const isUSD = broker === 'deltaexchange'
  ... Intl.NumberFormat with currency: isUSD ? 'USD' : 'INR'

# Live-data fallback paths (acceptable pattern — REST-on-WS-failure, not capability fallback)
frontend/src/lib/MarketDataManager.ts:9,124-130,198-251,425-698,726-831
frontend/src/hooks/useLivePrice.ts:31,53,64,147,209
frontend/src/hooks/useLiveQuote.ts:43,45,69,85,115
frontend/src/components/trading/PlaceOrderDialog.tsx:121,238
frontend/src/pages/Holdings.tsx:53
frontend/src/pages/Positions.tsx:167
frontend/src/pages/StrategyBuilder.tsx:774
  These fall back from WS → REST; they are transport fallbacks and NOT
  capability fallbacks. Keep as-is.
```

## Blast radius

- **Phase 1b (plugin capabilities)** — `GET /api/broker/capabilities`
  enriches its response shape. Legacy keys stay.
- **Phase 5 (frontend)** — `useSupportedExchanges.ts` replaces
  `FALLBACK_EXCHANGES` with `capabilities.supported_venue_codes`;
  `defaultExchange` comes from the capability set, not a hardcoded
  `'NSE'`; `brokerStore.ts` surfaces load failure and pages skeleton
  rather than "show all". `frontend/src/lib/utils.ts:27-42` becomes a
  capability-driven formatter that reads `base_currency` off the
  capability object.
- **Phase 7 (analyzer gating)** — the capability store gates the
  Analyzer menu entry.

Invariant: new frontend code must not hardcode exchange or currency
names. Read everything from `brokerStore.capabilities`.
