import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeTab, useWorkspaceStore } from '../../state/workspaceStore'
import { useChartPersistence } from '../useChartPersistence'

function HookHost(props: { fetchImpl: typeof fetch; getApiKey: () => string | null }) {
  useChartPersistence({ fetchImpl: props.fetchImpl, getApiKey: props.getApiKey })
  return null
}

beforeEach(() => {
  vi.useFakeTimers()
  const fresh = makeTab('Workspace', '1')
  useWorkspaceStore.getState().hydrate({ tabs: [fresh], activeTabId: fresh.id, theme: 'dark' })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useChartPersistence', () => {
  it('skips persistence when no apikey is present', () => {
    const fetchImpl = vi.fn(async () => new Response('{}', { status: 200 }))
    render(<HookHost fetchImpl={fetchImpl as unknown as typeof fetch} getApiKey={() => null} />)
    // Trigger a state change.
    act(() => {
      const t = useWorkspaceStore.getState().tabs[0]
      useWorkspaceStore.getState().setTemplate(t.id, '4-quad')
    })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('debounces persistence at ~500ms after a state change', async () => {
    const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/active-layout')) {
        return new Response(JSON.stringify({ data: { user_id: 'u', layout_id: null } }), {
          status: 200,
        })
      }
      if (u.includes('/api/v2/chart/layouts') && init?.method === 'POST') {
        return new Response(JSON.stringify({ data: { id: 1 } }), { status: 201 })
      }
      return new Response(JSON.stringify({ data: {} }), { status: 200 })
    })
    render(
      <HookHost fetchImpl={fetchImpl as unknown as typeof fetch} getApiKey={() => 'apikey-x'} />
    )

    // Hydrate effect fires immediately (active-layout fetch).
    await act(async () => {
      await Promise.resolve()
    })
    fetchImpl.mockClear()

    // State change.
    act(() => {
      const t = useWorkspaceStore.getState().tabs[0]
      useWorkspaceStore.getState().setTemplate(t.id, '4-quad')
    })
    // Before 500ms — no save yet.
    expect(fetchImpl).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(490)
      await Promise.resolve()
    })
    expect(fetchImpl).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(20)
      await Promise.resolve()
      await Promise.resolve()
    })
    // The save call (POST to /api/v2/chart/layouts) should fire now.
    expect(fetchImpl.mock.calls.some((c) => String(c[0]).includes('/chart/layouts'))).toBe(true)
  })
})
