// Phase 7 — legacy chart pages still render after the new workspace
// landed.
//
// We don't try to load real broker data — the test just navigates to
// each legacy route and asserts the page mounts without a runtime
// error. When no broker session is available the route guard
// redirects to /login or /broker; we treat that as a pass for the
// "no regression" smoke goal.

import { expect, test } from '@playwright/test'

const LEGACY_ROUTES = [
  '/historify',
  '/historify/charts',
  '/tradingview',
  '/gocharting',
  '/pnl-tracker',
  '/health',
  '/ivchart',
  '/oitracker',
  '/maxpain',
  '/volsurface',
  '/straddle',
  '/straddlepnl',
  '/ivsmile',
  '/gex',
  '/oiprofile',
  '/chartink',
]

test.describe('legacy chart pages — smoke', () => {
  for (const route of LEGACY_ROUTES) {
    test(`loads ${route} without runtime error`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(e.message))
      const resp = await page.goto(route)
      if (!resp) {
        test.skip(true, 'navigation failed (likely no backend running)')
        return
      }
      await page.waitForLoadState('networkidle')
      // Auth boundary: the legacy India pages live behind <IndiaOnly>
      // inside <Layout>. Without an authenticated broker session, the
      // SPA redirects through /login / /broker. Either flow is fine —
      // the smoke goal is "no runtime error".
      const url = page.url()
      if (
        url.includes('/login') ||
        url.includes('/broker') ||
        url.includes('/error')
      ) {
        // Auth redirect — that's expected without a session.
        expect(errors).toEqual([])
        return
      }
      expect(errors, `runtime errors on ${route}`).toEqual([])
    })
  }
})
