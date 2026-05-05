import { describe, expect, it } from 'vitest'
import { CANONICAL_INTERVALS, supportedForBroker, translateForBroker } from '../intervals'

describe('canonical interval vocabulary (D-08)', () => {
  it('contains every interval in HANDOFF D-08', () => {
    const expected = new Set([
      '1s',
      '5s',
      '15s',
      '30s',
      '1m',
      '2m',
      '3m',
      '5m',
      '10m',
      '15m',
      '30m',
      '1h',
      '2h',
      '4h',
      '1d',
      '1w',
      '1mo',
    ])
    expect(new Set(CANONICAL_INTERVALS as readonly string[])).toEqual(expected)
  })
})

describe('zerodha translation', () => {
  it.each([
    ['1m', 'minute'],
    ['3m', '3minute'],
    ['15m', '15minute'],
    ['1h', '60minute'],
    ['1d', 'day'],
  ])('translates %s → %s', (canonical, native) => {
    expect(translateForBroker(canonical as never, 'zerodha')).toBe(native)
  })

  it('returns null for unsupported intervals', () => {
    expect(translateForBroker('2h', 'zerodha')).toBeNull()
  })
})

describe('alpaca translation', () => {
  it.each([
    ['1m', '1Min'],
    ['5m', '5Min'],
    ['1h', '1Hour'],
    ['1d', '1Day'],
    ['1w', '1Week'],
    ['1mo', '1Month'],
  ])('translates %s → %s', (canonical, native) => {
    expect(translateForBroker(canonical as never, 'alpaca')).toBe(native)
  })

  it('returns null for sub-minute and 2m intervals', () => {
    expect(translateForBroker('2m', 'alpaca')).toBeNull()
    expect(translateForBroker('1s', 'alpaca')).toBeNull()
  })
})

describe('supportedForBroker', () => {
  it('returns only translated intervals', () => {
    const z = supportedForBroker('zerodha')
    expect(z).toContain('1m')
    expect(z).toContain('1d')
    expect(z).not.toContain('2h')
    const a = supportedForBroker('alpaca')
    expect(a).toContain('1mo')
    expect(a).not.toContain('2m')
  })
})
