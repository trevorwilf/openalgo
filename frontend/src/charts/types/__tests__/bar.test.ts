import { describe, expect, it } from 'vitest'
import { decStrToNumber, isNormalizedBar, type NormalizedBar } from '../bar'
import {
  intervalSeconds,
  isCanonicalInterval,
  millisToSeconds,
  secondsToMillis,
  utcMillis,
  utcSeconds,
} from '../interval'
import { isNormalizedQuote, type NormalizedQuote } from '../quote'
import { isNormalizedTick } from '../tick'

describe('NormalizedBar', () => {
  it('round-trips through JSON with decimal-string fields preserved', () => {
    const b: NormalizedBar = {
      t: utcSeconds(1700000000),
      o: '100.250000001',
      h: '101.500000002',
      l: '99.750000003',
      c: '100.875000004',
      v: '12345',
      oi: null,
    }
    const parsed = JSON.parse(JSON.stringify(b))
    expect(isNormalizedBar(parsed)).toBe(true)
    // Decimal precision survives because we use string at the wire layer.
    expect(parsed.o).toBe('100.250000001')
  })

  it('rejects shapes with numeric (not string) decimals', () => {
    const wrong = { t: 1, o: 100, h: 1, l: 1, c: 1, v: 1, oi: null }
    expect(isNormalizedBar(wrong)).toBe(false)
  })

  it('decStrToNumber returns null for null input and a number for valid string', () => {
    expect(decStrToNumber(null)).toBeNull()
    expect(decStrToNumber('12.5')).toBe(12.5)
    expect(decStrToNumber('not-a-number')).toBeNull()
  })
})

describe('NormalizedQuote', () => {
  it('isNormalizedQuote accepts well-formed shape', () => {
    const q: NormalizedQuote = {
      t: utcSeconds(1700000000),
      bid: '100.0',
      ask: '100.5',
      last: '100.25',
      bid_size: '10',
      ask_size: '20',
      last_size: '5',
      volume_today: '12345',
    }
    expect(isNormalizedQuote(q)).toBe(true)
  })

  it('isNormalizedQuote allows null for any decimal field', () => {
    const q: NormalizedQuote = {
      t: utcSeconds(1700000000),
      bid: null,
      ask: null,
      last: '100.25',
      bid_size: null,
      ask_size: null,
      last_size: null,
      volume_today: null,
    }
    expect(isNormalizedQuote(q)).toBe(true)
  })

  it('isNormalizedQuote rejects numeric (not string) decimals', () => {
    expect(
      isNormalizedQuote({
        t: 1,
        bid: 100,
        ask: null,
        last: null,
        bid_size: null,
        ask_size: null,
        last_size: null,
        volume_today: null,
      })
    ).toBe(false)
  })
})

describe('NormalizedTick', () => {
  it('accepts each tick kind', () => {
    for (const kind of ['trade', 'quote', 'bar_forming', 'bar_closed']) {
      expect(isNormalizedTick({ kind, symbol: 'AAPL', t: 1700000000000, payload: {} })).toBe(true)
    }
  })

  it('rejects unknown kind', () => {
    expect(isNormalizedTick({ kind: 'panic', symbol: 'AAPL', t: 1, payload: {} })).toBe(false)
  })
})

describe('Interval helpers', () => {
  it('seconds <-> millis round trip', () => {
    const s = utcSeconds(1700000000)
    const ms = secondsToMillis(s)
    expect(ms).toBe(utcMillis(1700000000000))
    expect(millisToSeconds(ms)).toBe(s)
  })

  it('intervalSeconds returns null only for 1mo (calendar-aware)', () => {
    expect(intervalSeconds('1m')).toBe(60)
    expect(intervalSeconds('1h')).toBe(3600)
    expect(intervalSeconds('1d')).toBe(86400)
    expect(intervalSeconds('1w')).toBe(604800)
    expect(intervalSeconds('1mo')).toBeNull()
  })

  it('isCanonicalInterval narrows correctly', () => {
    expect(isCanonicalInterval('1m')).toBe(true)
    expect(isCanonicalInterval('1minute')).toBe(false)
  })
})
