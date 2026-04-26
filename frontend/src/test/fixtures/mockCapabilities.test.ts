// Phase 6 v4 (ADR 0023) — sanity tests for the capability fixtures.
//
// Confirms shape stability and that no India literals appear in the
// non-India fixtures' visible string fields. New fixtures added here
// must keep the assertions green.

import { describe, expect, it } from 'vitest'

import {
  ALL_CAPABILITIES_FIXTURES,
  EU_CAPABILITIES_FIXTURE,
  INDIA_CAPABILITIES_FIXTURE,
  UK_CAPABILITIES_FIXTURE,
  US_CAPABILITIES_FIXTURE,
} from './mockCapabilities'

const INDIA_LITERALS = [
  'NSE',
  'NFO',
  'BSE',
  'BFO',
  'MCX',
  'CDS',
  'INR',
  '₹',
  'NIFTY',
  'BANKNIFTY',
  'MIS',
  'CNC',
  'NRML',
]

function flattenStrings(obj: unknown): string[] {
  if (typeof obj === 'string') return [obj]
  if (Array.isArray(obj)) return obj.flatMap(flattenStrings)
  if (obj && typeof obj === 'object') {
    return Object.values(obj).flatMap(flattenStrings)
  }
  return []
}

describe('mockCapabilities fixtures', () => {
  it('exports fixtures for india, us, eu, uk', () => {
    expect(ALL_CAPABILITIES_FIXTURES.india).toBe(INDIA_CAPABILITIES_FIXTURE)
    expect(ALL_CAPABILITIES_FIXTURES.us).toBe(US_CAPABILITIES_FIXTURE)
    expect(ALL_CAPABILITIES_FIXTURES.eu).toBe(EU_CAPABILITIES_FIXTURE)
    expect(ALL_CAPABILITIES_FIXTURES.uk).toBe(UK_CAPABILITIES_FIXTURE)
    expect(ALL_CAPABILITIES_FIXTURES.unsupported).toBeNull()
  })

  it('india fixture uses India venues + INR', () => {
    expect(INDIA_CAPABILITIES_FIXTURE.default_currency).toBe('INR')
    expect(INDIA_CAPABILITIES_FIXTURE.supported_venue_codes).toContain('NSE')
  })

  it('us fixture has zero india literals in any visible string', () => {
    const all = flattenStrings(US_CAPABILITIES_FIXTURE).join('|')
    for (const lit of INDIA_LITERALS) {
      // Use word-boundary match where appropriate.
      const re = new RegExp(`\\b${lit}\\b`, 'i')
      expect(all).not.toMatch(re)
    }
  })

  it('eu fixture has zero india literals', () => {
    const all = flattenStrings(EU_CAPABILITIES_FIXTURE).join('|')
    for (const lit of INDIA_LITERALS) {
      const re = new RegExp(`\\b${lit}\\b`, 'i')
      expect(all).not.toMatch(re)
    }
  })

  it('uk fixture has zero india literals', () => {
    const all = flattenStrings(UK_CAPABILITIES_FIXTURE).join('|')
    for (const lit of INDIA_LITERALS) {
      const re = new RegExp(`\\b${lit}\\b`, 'i')
      expect(all).not.toMatch(re)
    }
  })

  it('us fixture supports extended hours and short selling', () => {
    expect(US_CAPABILITIES_FIXTURE.supports_extended_hours).toBe(true)
    expect(US_CAPABILITIES_FIXTURE.supports_short_selling).toBe(true)
  })
})
