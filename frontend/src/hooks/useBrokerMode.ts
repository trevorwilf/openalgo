/**
 * Resolve the active broker session's paper-vs-live mode.
 *
 * The header renders a yellow ``PAPER`` pill (or red ``LIVE``) so the
 * operator never has to guess which environment they're connected
 * to. Backend computes the mode from broker-specific signals (Alpaca
 * key prefix, env vars, etc.) — see
 * ``services/broker_mode_resolver.py``. This hook fetches it once
 * per session.
 */

import { useEffect, useState } from 'react'

export type BrokerMode = 'paper' | 'live' | 'unknown'

interface BrokerModeState {
  mode: BrokerMode
  isLoaded: boolean
}

let _cache: BrokerModeState | null = null

/** Read the active broker's mode from ``/auth/broker-config``. The
 * fetch happens at most once per page load (cached at module level)
 * because the mode doesn't change without a restart. Components
 * that mount later still get the resolved value synchronously after
 * the first fetch.
 */
export function useBrokerMode(): BrokerModeState {
  const [state, setState] = useState<BrokerModeState>(
    _cache ?? { mode: 'unknown', isLoaded: false },
  )

  useEffect(() => {
    if (_cache) return
    let cancelled = false

    fetch('/auth/broker-config', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (cancelled || !body) return
        const mode: BrokerMode =
          body.broker_mode === 'paper'
          || body.broker_mode === 'live'
          || body.broker_mode === 'unknown'
            ? body.broker_mode
            : 'unknown'
        const next = { mode, isLoaded: true }
        _cache = next
        setState(next)
      })
      .catch(() => {
        if (cancelled) return
        const next: BrokerModeState = { mode: 'unknown', isLoaded: true }
        _cache = next
        setState(next)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return state
}

/** Test-only escape hatch — clear the module-level cache so the next
 * mount re-fetches. Not exported from index files; reserved for
 * unit tests that want to assert the loading-state behavior. */
export function _resetBrokerModeCacheForTests(): void {
  _cache = null
}
