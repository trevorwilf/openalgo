import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { IndicatorManager } from '../IndicatorManager'

describe('<IndicatorManager>', () => {
  it('renders nothing when open=false', () => {
    const { container } = render(
      <IndicatorManager
        cellId="c1"
        layoutId={1}
        apikey="k"
        open={false}
        onClose={() => undefined}
        fetchImpl={vi.fn() as unknown as typeof fetch}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders catalog and lists current rows', async () => {
    const fetchImpl = vi.fn(
      async () =>
        ({
          ok: true,
          async json() {
            return {
              data: [
                {
                  id: 5,
                  layout_id: 1,
                  cell_id: 'c1',
                  indicator_key: 'RSI',
                  params_json: { period: 14 },
                },
              ],
            }
          },
        }) as unknown as Response
    )
    render(
      <IndicatorManager
        cellId="c1"
        layoutId={1}
        apikey="k"
        open
        onClose={() => undefined}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />
    )
    await waitFor(() => {
      expect(screen.getByTestId('indicator-row-5')).toBeTruthy()
    })
    expect(screen.getByTestId('indicator-picker')).toBeTruthy()
  })

  it('submits POST when Add is clicked', async () => {
    const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return {
          ok: true,
          async json() {
            return { data: { id: 9 } }
          },
        } as unknown as Response
      }
      return {
        ok: true,
        async json() {
          return { data: [] }
        },
      } as unknown as Response
    })
    const onClose = vi.fn()
    render(
      <IndicatorManager
        cellId="c1"
        layoutId={1}
        apikey="k"
        open
        onClose={onClose}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />
    )
    fireEvent.click(screen.getByTestId('indicator-add'))
    await waitFor(() => {
      const postCalls = fetchImpl.mock.calls.filter(
        (c) => (c[1] as RequestInit | undefined)?.method === 'POST'
      )
      expect(postCalls.length).toBe(1)
    })
  })
})
