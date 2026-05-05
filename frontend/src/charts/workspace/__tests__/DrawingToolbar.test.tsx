import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DrawingToolbar } from '../DrawingToolbar'

describe('<DrawingToolbar>', () => {
  it('renders all 9 drawing kinds', () => {
    render(<DrawingToolbar />)
    for (const kind of [
      'trendline',
      'horizontal',
      'vertical',
      'ray',
      'rectangle',
      'ellipse',
      'fib_retracement',
      'fib_extension',
      'text',
    ]) {
      expect(screen.getByTestId(`draw-tool-${kind}`)).toBeTruthy()
    }
  })

  it('toggles the active kind on click + click-again deactivates', () => {
    const onPick = vi.fn()
    render(<DrawingToolbar onPickKind={onPick} />)
    const btn = screen.getByTestId('draw-tool-rectangle')
    fireEvent.click(btn)
    expect(btn.getAttribute('data-active')).toBe('true')
    expect(onPick).toHaveBeenLastCalledWith('rectangle')
    fireEvent.click(btn)
    expect(btn.getAttribute('data-active')).toBe('false')
    expect(onPick).toHaveBeenLastCalledWith(null)
  })
})
