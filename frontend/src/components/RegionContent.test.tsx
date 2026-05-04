/**
 * Unit tests for ``RegionContent`` + ``pickRegionValue``.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RegionContent, pickRegionValue } from './RegionContent'

vi.mock('@/hooks/useBrokerRegion', () => ({
  useBrokerRegion: vi.fn(),
}))

import { useBrokerRegion } from '@/hooks/useBrokerRegion'

describe('RegionContent', () => {
  it('renders children for india region', () => {
    vi.mocked(useBrokerRegion).mockReturnValue('india')
    render(
      <RegionContent us={<div>US</div>} eu={<div>EU</div>}>
        <div>India</div>
      </RegionContent>,
    )
    expect(screen.getByText('India')).toBeInTheDocument()
    expect(screen.queryByText('US')).not.toBeInTheDocument()
  })

  it('renders us slot when region is us', () => {
    vi.mocked(useBrokerRegion).mockReturnValue('us')
    render(
      <RegionContent us={<div>US</div>}>
        <div>India</div>
      </RegionContent>,
    )
    expect(screen.getByText('US')).toBeInTheDocument()
    expect(screen.queryByText('India')).not.toBeInTheDocument()
  })

  it('falls back to children when region is us but no us slot', () => {
    vi.mocked(useBrokerRegion).mockReturnValue('us')
    render(
      <RegionContent>
        <div>Default</div>
      </RegionContent>,
    )
    expect(screen.getByText('Default')).toBeInTheDocument()
  })

  it('renders loading slot for unknown region', () => {
    vi.mocked(useBrokerRegion).mockReturnValue('unknown')
    render(
      <RegionContent loading={<div>Loading...</div>} us={<div>US</div>}>
        <div>India</div>
      </RegionContent>,
    )
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })
})

describe('pickRegionValue', () => {
  it('picks the matching region value', () => {
    expect(
      pickRegionValue('us', {
        india: 'i',
        us: 'u',
        default: 'd',
      }),
    ).toBe('u')
  })

  it('falls back to default when no region match', () => {
    expect(
      pickRegionValue('eu', {
        india: 'i',
        us: 'u',
        default: 'd',
      }),
    ).toBe('d')
  })

  it('returns undefined when no default and no match', () => {
    expect(pickRegionValue('uk', { india: 'i' })).toBeUndefined()
  })
})
