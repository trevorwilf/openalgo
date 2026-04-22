import { LayoutDashboard } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import {
  bottomNavItems,
  filterNavByCapabilities,
  isActiveRoute,
  mobileSheetItems,
  type NavItem,
  navItems,
  profileMenuItems,
} from './navigation'

describe('Navigation Config', () => {
  describe('navItems', () => {
    it('contains the expected main navigation items', () => {
      expect(navItems).toHaveLength(9)

      const labels = navItems.map((item) => item.label)
      expect(labels).toContain('Dashboard')
      expect(labels).toContain('Tools')
      expect(labels).toContain('Orderbook')
      expect(labels).toContain('Positions')
      expect(labels).toContain('Strategy')
    })

    it('all items have required properties', () => {
      navItems.forEach((item) => {
        expect(item).toHaveProperty('href')
        expect(item).toHaveProperty('label')
        expect(item).toHaveProperty('icon')
        expect(item.href).toMatch(/^\//)
        expect(item.label.length).toBeGreaterThan(0)
      })
    })
  })

  describe('bottomNavItems', () => {
    it('contains exactly 5 items for mobile bottom nav', () => {
      expect(bottomNavItems).toHaveLength(5)
    })

    it('has the correct order: Dashboard, Orderbook, Tradebook, Positions, Strategy', () => {
      const labels = bottomNavItems.map((item) => item.label)
      expect(labels).toEqual(['Dashboard', 'Orderbook', 'Tradebook', 'Positions', 'Strategy'])
    })
  })

  describe('mobileSheetItems', () => {
    it('excludes items already in bottomNavItems', () => {
      const bottomPaths = bottomNavItems.map((item) => item.href)
      const sheetPaths = mobileSheetItems.map((item) => item.href)

      sheetPaths.forEach((path) => {
        expect(bottomPaths).not.toContain(path)
      })
    })

    it('contains remaining nav items', () => {
      const sheetLabels = mobileSheetItems.map((item) => item.label)
      expect(sheetLabels).toContain('Action Center')
      expect(sheetLabels).toContain('Platforms')
      expect(sheetLabels).toContain('Logs')
    })
  })

  describe('profileMenuItems', () => {
    it('contains profile-related menu items', () => {
      const labels = profileMenuItems.map((item) => item.label)
      expect(labels).toContain('Profile')
      expect(labels).toContain('API Key')
      expect(labels).toContain('Holdings')
    })
  })

  describe('filterNavByCapabilities', () => {
    const item = (overrides: Partial<NavItem> = {}): NavItem => ({
      href: '/test',
      label: 'Test',
      icon: LayoutDashboard,
      ...overrides,
    })
    const plain = item()
    const gated = item({
      href: '/sandbox',
      label: 'Sandbox',
      capability: 'supports_analyzer',
    })

    it('keeps items without a capability field', () => {
      const out = filterNavByCapabilities([plain, gated], { supports_analyzer: true })
      expect(out.map((i) => i.href)).toEqual(['/test', '/sandbox'])
    })

    it('drops gated items when the capability is false', () => {
      const out = filterNavByCapabilities([plain, gated], { supports_analyzer: false })
      expect(out.map((i) => i.href)).toEqual(['/test'])
    })

    it('fails closed when capabilities are null or undefined', () => {
      expect(filterNavByCapabilities([plain, gated], null).map((i) => i.href)).toEqual(['/test'])
      expect(filterNavByCapabilities([plain, gated], undefined).map((i) => i.href)).toEqual([
        '/test',
      ])
    })

    it('falls through to features dict for custom flags', () => {
      const customGated = item({ capability: 'custom_flag' })
      expect(
        filterNavByCapabilities([customGated], { features: { custom_flag: true } })
      ).toHaveLength(1)
      expect(filterNavByCapabilities([customGated], { features: { custom_flag: false } })).toEqual(
        []
      )
    })

    it('hides items when the capability key exists on neither first-class nor features', () => {
      const customGated = item({ capability: 'unknown_capability' })
      expect(filterNavByCapabilities([customGated], { features: {} })).toEqual([])
    })

    it('the Sandbox nav item carries supports_analyzer as its gate', () => {
      const sandbox = profileMenuItems.find((i) => i.href === '/sandbox')
      expect(sandbox).toBeDefined()
      expect(sandbox?.capability).toBe('supports_analyzer')
    })
  })

  describe('isActiveRoute', () => {
    it('returns true for exact matches', () => {
      expect(isActiveRoute('/dashboard', '/dashboard')).toBe(true)
      expect(isActiveRoute('/orderbook', '/orderbook')).toBe(true)
      expect(isActiveRoute('/positions', '/positions')).toBe(true)
    })

    it('returns false for non-matching routes', () => {
      expect(isActiveRoute('/dashboard', '/orderbook')).toBe(false)
      expect(isActiveRoute('/positions', '/holdings')).toBe(false)
    })

    it('handles /strategy route with prefix matching', () => {
      // Strategy route should match nested pages
      expect(isActiveRoute('/strategy', '/strategy')).toBe(true)
      expect(isActiveRoute('/strategy/new', '/strategy')).toBe(true)
      expect(isActiveRoute('/strategy/123', '/strategy')).toBe(true)
      expect(isActiveRoute('/strategy/123/configure', '/strategy')).toBe(true)
    })

    it('does not prefix match non-strategy routes', () => {
      // Other routes should not prefix match
      expect(isActiveRoute('/dashboard/sub', '/dashboard')).toBe(false)
      expect(isActiveRoute('/orderbookextra', '/orderbook')).toBe(false)
    })
  })
})
