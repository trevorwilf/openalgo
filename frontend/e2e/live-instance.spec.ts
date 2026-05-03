/**
 * Live-instance smoke against an already-running Flask server (default
 * http://127.0.0.1:5000). Unlike the other e2e specs this one does NOT
 * spawn its own dev server — it expects the operator's `uv run app.py`
 * to already be up.
 *
 * Run:
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:5000 npx playwright test \
 *     live-instance.spec.ts --project=chromium
 *
 * The tests:
 *  1. Capture every console error / 4xx-5xx network response per route.
 *  2. Visit the unauthenticated routes the React Router knows about.
 *  3. Probe known JSON endpoints for non-2xx responses.
 *  4. Take a screenshot of each route to ./test-results-live/ for
 *     after-the-fact human inspection.
 */
import { expect, test } from '@playwright/test'

const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000'

interface PageObservations {
  consoleErrors: string[]
  networkFailures: { url: string; status: number; method: string }[]
}

function attachObservers(page: import('@playwright/test').Page): PageObservations {
  const obs: PageObservations = { consoleErrors: [], networkFailures: [] }
  page.on('console', (msg) => {
    if (msg.type() === 'error') obs.consoleErrors.push(msg.text())
  })
  page.on('response', (resp) => {
    const status = resp.status()
    if (status >= 400 && status < 600) {
      obs.networkFailures.push({
        url: resp.url(),
        status,
        method: resp.request().method(),
      })
    }
  })
  return obs
}

test.describe.configure({ mode: 'serial' })

test.describe('Live Flask instance — unauthenticated routes', () => {
  const routes = [
    { path: '/', name: 'root' },
    { path: '/login', name: 'login' },
    { path: '/setup', name: 'setup' },
    { path: '/reset-password', name: 'reset-password' },
    { path: '/faq', name: 'faq' },
    { path: '/download', name: 'download' },
  ]

  for (const route of routes) {
    test(`route ${route.path} loads + has no console errors`, async ({ page }) => {
      const obs = attachObservers(page)
      const resp = await page.goto(`${BASE}${route.path}`)
      expect(resp).not.toBeNull()
      expect(resp!.status(), `${route.path} HTTP status`).toBeLessThan(400)
      await page.waitForLoadState('networkidle')

      // React mount sentinel
      await expect(page.locator('#root')).toBeAttached()

      // Body shouldn't be empty after networkidle
      const bodyText = await page.locator('body').innerText()
      expect(
        bodyText.length,
        `${route.path} body innerText length`,
      ).toBeGreaterThan(0)

      // Take a screenshot for human review
      await page.screenshot({
        path: `test-results-live/${route.name}.png`,
        fullPage: true,
      })

      // Don't fail on every console error — many React libs warn —
      // but DO fail on 5xx network responses.
      const fiveXX = obs.networkFailures.filter((f) => f.status >= 500)
      expect(
        fiveXX,
        `${route.path} 5xx responses: ${JSON.stringify(fiveXX, null, 2)}`,
      ).toEqual([])

      // Log everything for the human reading the report
      if (obs.consoleErrors.length > 0) {
        console.log(
          `[${route.path}] console errors:\n  - ${obs.consoleErrors.join('\n  - ')}`,
        )
      }
      if (obs.networkFailures.length > 0) {
        console.log(
          `[${route.path}] network failures (4xx+5xx):\n  ${JSON.stringify(obs.networkFailures, null, 2)}`,
        )
      }
    })
  }
})

test.describe('Live Flask instance — JSON endpoints', () => {
  const endpoints = [
    { path: '/auth/check-setup', expectKeys: ['status', 'needs_setup'] },
    { path: '/auth/broker-config', expectKeys: ['status', 'broker_name'] },
    { path: '/auth/csrf-token', expectKeys: ['csrf_token'] },
    { path: '/api/docs', expectKeys: [] },
  ]

  for (const ep of endpoints) {
    test(`endpoint ${ep.path} returns 2xx + expected shape`, async ({
      request,
    }) => {
      const resp = await request.get(`${BASE}${ep.path}`)
      expect(resp.status(), `${ep.path}`).toBeLessThan(400)
      if (ep.expectKeys.length > 0) {
        const body = await resp.json()
        for (const key of ep.expectKeys) {
          expect(body, `${ep.path} missing ${key}`).toHaveProperty(key)
        }
      }
    })
  }
})
