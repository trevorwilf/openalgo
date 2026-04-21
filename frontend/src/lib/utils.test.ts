import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  _resetDeprecationWarningForTests,
  cn,
  formatCurrencyByCode,
  makeFormatCurrency,
  sanitizeCSV,
} from './utils'

describe('cn', () => {
  it('merges tailwind class names', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })
})

describe('sanitizeCSV', () => {
  it('prefixes formula-trigger characters', () => {
    expect(sanitizeCSV('=1+1')).toBe("'=1+1")
    expect(sanitizeCSV('@SUM(A1)')).toBe("'@SUM(A1)")
    expect(sanitizeCSV('-5')).toBe("'-5")
  })

  it('wraps comma-containing strings in quotes', () => {
    expect(sanitizeCSV('a,b')).toBe('"a,b"')
  })

  it('passes plain values through', () => {
    expect(sanitizeCSV('RELIANCE')).toBe('RELIANCE')
    expect(sanitizeCSV(42)).toBe('42')
    expect(sanitizeCSV(null)).toBe('')
    expect(sanitizeCSV(undefined)).toBe('')
  })
})

describe('formatCurrencyByCode', () => {
  it('formats INR with 2 decimals', () => {
    const out = formatCurrencyByCode(1234.5, 'INR')
    expect(out).toContain('1,234.50')
    // Some runtimes use ₹, others use "INR"; both are acceptable.
    expect(out).toMatch(/(₹|INR)/)
  })

  it('formats USD with $', () => {
    const out = formatCurrencyByCode(1234.5, 'USD')
    expect(out).toContain('1,234.50')
    expect(out).toMatch(/\$/)
  })

  it('formats EUR', () => {
    const out = formatCurrencyByCode(1234.5, 'EUR')
    expect(out).toMatch(/(€|EUR)/)
  })

  it('formats USDT with the ticker suffix', () => {
    expect(formatCurrencyByCode(99, 'USDT')).toBe('99.00 USDT')
  })

  it('formats USDC with the ticker suffix', () => {
    expect(formatCurrencyByCode(99, 'USDC')).toBe('99.00 USDC')
  })

  it('formats BTC with 8 decimals', () => {
    expect(formatCurrencyByCode(0.12345678, 'BTC')).toBe('0.12345678 BTC')
  })

  it('formats ETH with 6 decimals', () => {
    expect(formatCurrencyByCode(1.234567891, 'ETH')).toBe('1.234568 ETH')
  })

  it('formats JPY with 0 decimals', () => {
    const out = formatCurrencyByCode(1234, 'JPY')
    // Should have no fractional portion. Accept either ¥ or JPY.
    expect(out).not.toMatch(/\./)
  })

  it('respects explicit locale override', () => {
    const us = formatCurrencyByCode(1234.5, 'EUR', 'en-US')
    expect(us).toContain('1,234.50')
  })
})

describe('makeFormatCurrency (deprecated)', () => {
  beforeEach(() => {
    _resetDeprecationWarningForTests()
  })

  afterEach(() => {
    _resetDeprecationWarningForTests()
  })

  it('still returns an INR formatter for plain brokers', () => {
    const fmt = makeFormatCurrency('zerodha')
    const out = fmt(1234.5)
    expect(out).toContain('1,234.50')
    expect(out).toMatch(/(₹|INR)/)
  })

  it('returns a USD formatter for deltaexchange', () => {
    const fmt = makeFormatCurrency('deltaexchange')
    const out = fmt(1234.5)
    expect(out).toContain('1,234.50')
    expect(out).toMatch(/\$/)
  })

  it('emits a deprecation warning once per session', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    makeFormatCurrency('zerodha')
    makeFormatCurrency('zerodha')
    makeFormatCurrency('deltaexchange')
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy.mock.calls[0][0]).toContain('formatCurrencyByCode')
    spy.mockRestore()
  })

  it('accepts null broker and defaults to INR', () => {
    const fmt = makeFormatCurrency(null)
    const out = fmt(10)
    expect(out).toContain('10.00')
  })
})
