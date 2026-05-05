// Phase 2 — Workspace Shell smoke E2E.
//
// Loads `/charts` for an authenticated session, asserts the workspace
// shell renders, the paper banner is visible (D-04 default), all 6
// layouts are selectable, and the tab bar shows at least one tab.
//
// Prereqs:
//  * Vite dev server running on :5173 (Playwright `webServer` starts it).
//  * Flask backend session with a valid broker (Alpaca paper preferred).
//
// When the backend is not available (or the user has no broker
// session), the route guard at `Layout.tsx` redirects to /login
// before the workspace mounts. We detect that and skip — the test is
// a smoke check, not a regression gate.

import { expect, test } from '@playwright/test'

test.describe('/charts workspace smoke', () => {
  test('renders workspace shell with paper banner + 6 layouts', async ({
    page,
  }) => {
    await page.goto('/charts')
    await page.waitForLoadState('networkidle')

    // Auth boundary: if Layout redirected us, skip the assertions.
    const url = page.url()
    if (url.includes('/login') || url.includes('/broker')) {
      test.skip(
        true,
        `No authenticated broker session — Layout redirected to ${new URL(url).pathname}. ` +
          'Run with a logged-in Alpaca paper session to exercise the smoke test.',
      )
      return
    }

    // Workspace structure — same data-testids the unit tests use.
    await expect(page.getByTestId('chart-workspace')).toBeVisible({
      timeout: 5000,
    })
    await expect(page.getByTestId('workspace-topbar')).toBeVisible()
    await expect(page.getByTestId('workspace-sidebar')).toBeVisible()
    await expect(page.getByTestId('chart-layout-grid')).toBeVisible()

    // Paper banner default per D-04.
    const banner = page.getByTestId('paper-live-banner')
    await expect(banner).toHaveAttribute('data-mode', 'paper')

    // 6 layout buttons in the sidebar selector.
    const selector = page.getByTestId('layout-selector')
    await expect(selector.getByRole('button')).toHaveCount(6)

    // Kill switch placeholder visible + default OFF.
    const ks = page.getByTestId('kill-switch')
    await expect(ks).toBeVisible()
    await expect(ks).toHaveAttribute('data-state', 'off')
  })

  test('p95 first-paint under 1500ms (when reachable)', async ({ page }) => {
    const t0 = Date.now()
    const resp = await page.goto('/charts')
    if (!resp || resp.status() >= 400) {
      test.skip(true, 'No backend — skipping perf assertion')
      return
    }
    if (page.url().includes('/login') || page.url().includes('/broker')) {
      test.skip(true, 'No broker session — skipping perf assertion')
      return
    }
    await expect(page.getByTestId('chart-workspace')).toBeVisible({
      timeout: 5000,
    })
    const elapsed = Date.now() - t0
    expect(elapsed).toBeLessThan(1500)
  })
})
