import { describe, expect, it } from 'vitest'
import { utcSeconds } from '../../types/interval'
import { utcSecondsToDisplay } from '../timezone'

describe('utcSecondsToDisplay (P-06: no hardcoded IST literals)', () => {
  it('formats UTC for the UTC zone', () => {
    // 2024-01-01T00:00:00Z
    const ts = utcSeconds(1704067200)
    const parts = utcSecondsToDisplay(ts, 'UTC')
    expect(parts.date).toBe('2024-01-01')
    expect(parts.time).toBe('00:00:00')
    expect(parts.offsetMinutes).toBe(0)
  })

  it('resolves Indian venue tz from caller-supplied zone (NOT a literal)', () => {
    // 2024-01-01T00:00:00Z = 05:30 IST (UTC+5:30)
    const ts = utcSeconds(1704067200)
    const parts = utcSecondsToDisplay(ts, 'Asia/Calcutta')
    expect(parts.date).toBe('2024-01-01')
    expect(parts.time).toBe('05:30:00')
    expect(parts.offsetMinutes).toBe(330)
  })

  it('resolves America/New_York with DST awareness', () => {
    // 2024-07-01T17:00:00Z = 13:00 EDT (UTC-4)
    const summer = utcSeconds(1719853200)
    const summerParts = utcSecondsToDisplay(summer, 'America/New_York')
    expect(summerParts.time).toBe('13:00:00')
    expect(summerParts.offsetMinutes).toBe(-240)

    // 2024-01-15T17:00:00Z = 12:00 EST (UTC-5)
    const winter = utcSeconds(1705338000)
    const winterParts = utcSecondsToDisplay(winter, 'America/New_York')
    expect(winterParts.time).toBe('12:00:00')
    expect(winterParts.offsetMinutes).toBe(-300)
  })
})

// The forbidden-literal contract (no `5.5 * 60 * 60 * 1000`,
// 'Asia/Kolkata', 'IST') is enforced by `npm run lint:literals` at
// CI time, not in vitest. See frontend/scripts/literal_scan.mjs.
