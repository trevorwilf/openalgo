/**
 * Playwright configuration for testing against an already-running
 * Flask instance (the operator's `uv run app.py`). Unlike the default
 * config (which auto-spawns Vite dev server on :5173), this config:
 *
 *   - reads `baseURL` from `PLAYWRIGHT_BASE_URL` (defaults to
 *     http://127.0.0.1:5000)
 *   - does NOT spawn a webServer
 *   - only runs tests in `e2e/live-instance.spec.ts`
 *   - uses Chromium only (faster smoke; no need for cross-browser)
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config=playwright.live.config.ts
 */
import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000'

export default defineConfig({
  testDir: './e2e',
  testMatch: /(live-instance|auth-instance|paper-trading|paper-trading-actions|paper-trading-ui-click|paper-trading-positions|paper-trading-alpaca-parity|paper-trading-india-gating|paper-trading-mode-pill|paper-trading-fresh-login)\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report-live', open: 'never' }]],
  outputDir: 'test-results-live',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // No webServer — we expect the operator's Flask to already be up.
})
