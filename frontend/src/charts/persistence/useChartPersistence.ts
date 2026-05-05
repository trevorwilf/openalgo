// Phase 5 — chart persistence hook.
//
// Subscribes to the workspace store and persists the active layout's
// cells_json to /api/v2/chart/layouts on a 500ms debounce (HANDOFF
// D-06). On mount, the hook queries /api/v2/chart/active-layout and
// /api/v2/chart/layouts/<id> to hydrate the workspace store.
//
// The hook is a no-op when no apikey is in localStorage — the user
// can still drive the workspace fully in-browser; persistence only
// kicks in once they've signed in via /apikey.

import { useEffect, useRef } from 'react'
import { type TabState, useWorkspaceStore } from '../state/workspaceStore'

const DEBOUNCE_MS = 500

export interface PersistenceImpls {
  fetchImpl?: typeof fetch
  getApiKey?: () => string | null
}

function defaultGetApiKey(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem('openalgo:apikey')
}

interface ActiveLayoutResp {
  data: { user_id: string; layout_id: number | null }
}

interface LayoutResp {
  data: {
    id: number
    cells_json: { tabs?: TabState[]; activeTabId?: string | null; theme?: 'light' | 'dark' } | null
  }
}

/** Hook into the workspace store and round-trip cells_json to the
 *  backend. Returns the active layout id (so consumers can show "saved"
 *  / "saving" UX). */
export function useChartPersistence(impls: PersistenceImpls = {}): { layoutId: number | null } {
  const fetchFn = impls.fetchImpl ?? fetch
  const getApiKey = impls.getApiKey ?? defaultGetApiKey
  const layoutIdRef = useRef<number | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Hydrate on mount.
  useEffect(() => {
    let cancelled = false
    const apikey = getApiKey()
    if (!apikey) return undefined
    void hydrate(apikey, fetchFn).then((res) => {
      if (cancelled) return
      if (res) layoutIdRef.current = res.layoutId
    })
    return () => {
      cancelled = true
    }
  }, [fetchFn, getApiKey])

  // Save on any tabs / activeTabId / theme change.
  useEffect(() => {
    const apikey = getApiKey()
    if (!apikey) return undefined
    const unsub = useWorkspaceStore.subscribe((state) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        void persist(apikey, fetchFn, layoutIdRef, {
          tabs: state.tabs,
          activeTabId: state.activeTabId,
          theme: state.theme,
        })
      }, DEBOUNCE_MS)
    })
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      unsub()
    }
  }, [fetchFn, getApiKey])

  return { layoutId: layoutIdRef.current }
}

async function hydrate(
  apikey: string,
  fetchFn: typeof fetch
): Promise<{ layoutId: number | null } | null> {
  try {
    const activeRes = await fetchFn(
      `/api/v2/chart/active-layout?apikey=${encodeURIComponent(apikey)}`,
      {
        credentials: 'same-origin',
      }
    )
    if (!activeRes.ok) return { layoutId: null }
    const active = (await activeRes.json()) as ActiveLayoutResp
    const layoutId = active.data?.layout_id ?? null
    if (layoutId == null) return { layoutId: null }

    const layoutRes = await fetchFn(
      `/api/v2/chart/layouts/${layoutId}?apikey=${encodeURIComponent(apikey)}`,
      { credentials: 'same-origin' }
    )
    if (!layoutRes.ok) return { layoutId }
    const layout = (await layoutRes.json()) as LayoutResp
    const cells = layout.data?.cells_json ?? null
    if (cells && Array.isArray(cells.tabs)) {
      useWorkspaceStore.getState().hydrate({
        tabs: cells.tabs,
        activeTabId: cells.activeTabId ?? cells.tabs[0]?.id ?? null,
        theme: cells.theme ?? 'dark',
      })
    }
    return { layoutId }
  } catch {
    return null
  }
}

async function persist(
  apikey: string,
  fetchFn: typeof fetch,
  layoutIdRef: React.MutableRefObject<number | null>,
  payload: { tabs: TabState[]; activeTabId: string | null; theme: 'light' | 'dark' }
): Promise<void> {
  const cellsJson = {
    tabs: payload.tabs,
    activeTabId: payload.activeTabId,
    theme: payload.theme,
  }
  try {
    if (layoutIdRef.current == null) {
      const res = await fetchFn('/api/v2/chart/layouts', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          apikey,
          name: 'Default',
          schema_version: 1,
          cells_json: cellsJson,
        }),
      })
      if (!res.ok) return
      const json = (await res.json()) as { data?: { id: number } }
      const id = json.data?.id ?? null
      if (id != null) {
        layoutIdRef.current = id
        await fetchFn('/api/v2/chart/active-layout', {
          method: 'PUT',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ apikey, layout_id: id }),
        })
      }
    } else {
      await fetchFn(`/api/v2/chart/layouts/${layoutIdRef.current}`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apikey, cells_json: cellsJson }),
      })
    }
  } catch {
    // Ignore persistence errors — the workspace stays in-browser.
  }
}

export const __chartPersistenceTesting = { DEBOUNCE_MS, hydrate, persist }
