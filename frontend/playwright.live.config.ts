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
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000'

export default defineConfig({
  testDir: './e2e',
  // Cancel any leftover open orders on the Alpaca paper account
  // before any test runs. Otherwise wash-trade prevention rejects
  // the first deep-OOM LIMIT order with 403 / code=40310000.
  // Absolute path because Playwright workers (which re-load the
  // config from various cwds) sometimes fail to resolve a
  // ``./e2e/...`` relative path under ``"type": "module"``.
  globalSetup: path.resolve(__dirname, 'e2e', 'global-setup.ts'),
  testMatch: /(live-instance|auth-instance|paper-trading|paper-trading-actions|paper-trading-ui-click|paper-trading-positions|paper-trading-alpaca-parity|paper-trading-india-gating|paper-trading-mode-pill|paper-trading-fresh-login|paper-trading-ws-ticks)\.spec\.ts/,
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
