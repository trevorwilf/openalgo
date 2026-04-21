import { create } from 'zustand'
import type { BrokerCapabilities } from '@/types/capabilities'

interface BrokerStore {
  capabilities: BrokerCapabilities | null
  isLoaded: boolean
  /** Phase 5: fail-closed flag. `true` when the last fetch attempt finished
   * but did not produce a usable capability object (network error, non-OK
   * HTTP, invalid shape). Components should treat `isError && !capabilities`
   * as "capabilities unavailable — do not assume anything". */
  isError: boolean
  /** Human-readable reason for the error. Set when `isError` is true. */
  error: string | null

  fetchCapabilities: () => Promise<void>
  clearCapabilities: () => void
}

/**
 * Phase 5: fail-closed capability store.
 *
 * Prior behavior silently swallowed fetch errors and left
 * `capabilities: null`, which caused consumers to render every exchange
 * by default — a fail-open pattern where a backend hiccup could expose
 * UI controls for venues the broker does not support.
 *
 * New behavior: any fetch error sets `isError: true` with an `error`
 * message. Consumers must check `isError` before showing a generic
 * fallback; the default is "capabilities unavailable, hide
 * capability-dependent UI".
 */
export const useBrokerStore = create<BrokerStore>()((set) => ({
  capabilities: null,
  isLoaded: false,
  isError: false,
  error: null,

  fetchCapabilities: async () => {
    try {
      const response = await fetch('/api/broker/capabilities', {
        credentials: 'include',
      })

      if (!response.ok) {
        set({
          capabilities: null,
          isLoaded: true,
          isError: true,
          error: `HTTP ${response.status}: ${response.statusText}`,
        })
        return
      }

      const payload = (await response.json()) as unknown
      if (
        !payload ||
        typeof payload !== 'object' ||
        (payload as { status?: string }).status !== 'success' ||
        !(payload as { data?: unknown }).data
      ) {
        set({
          capabilities: null,
          isLoaded: true,
          isError: true,
          error: 'Invalid capability payload from /api/broker/capabilities',
        })
        return
      }

      set({
        capabilities: (payload as { data: BrokerCapabilities }).data,
        isLoaded: true,
        isError: false,
        error: null,
      })
    } catch (err) {
      set({
        capabilities: null,
        isLoaded: true,
        isError: true,
        error: err instanceof Error ? err.message : String(err),
      })
    }
  },

  clearCapabilities: () =>
    set({ capabilities: null, isLoaded: false, isError: false, error: null }),
}))
