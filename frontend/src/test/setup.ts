import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Cleanup after each test case
afterEach(() => {
  cleanup()
})

// Mock window.matchMedia for tests
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver — must be class-shaped so `new ResizeObserver(...)`
// works (react-resizable-panels and similar libraries instantiate it).
class MockResizeObserver {
  observe(): void {
    /* no-op */
  }
  unobserve(): void {
    /* no-op */
  }
  disconnect(): void {
    /* no-op */
  }
}
window.ResizeObserver = MockResizeObserver as unknown as typeof window.ResizeObserver

// Mock IntersectionObserver — same constructor-shape requirement.
class MockIntersectionObserver {
  readonly root: Element | null = null
  readonly rootMargin: string = ''
  readonly thresholds: readonly number[] = []
  observe(): void {
    /* no-op */
  }
  unobserve(): void {
    /* no-op */
  }
  disconnect(): void {
    /* no-op */
  }
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}
window.IntersectionObserver =
  MockIntersectionObserver as unknown as typeof window.IntersectionObserver

// Mock scrollTo
window.scrollTo = vi.fn()

// Mock clipboard API — happy-dom defines `navigator.clipboard` as a
// getter-only property, so `Object.assign` cannot overwrite it.
// Use `defineProperty` with `configurable: true` to replace it
// cleanly on both jsdom and happy-dom.
Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: {
    writeText: vi.fn().mockImplementation(() => Promise.resolve()),
    readText: vi.fn().mockImplementation(() => Promise.resolve('')),
  },
})
