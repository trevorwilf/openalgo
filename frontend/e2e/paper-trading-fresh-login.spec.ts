/**
 * Fresh-login flow — exercises the path a Monday-morning operator
 * actually walks through. Unlike the rest of the suite (which
 * shortcuts past the UI by reusing a saved storageState), this
 * test uses a clean browser context every time and clicks through
 * every step:
 *
 *   1. GET /login — public page, no session.
 *   2. Fill the username + password form fields.
 *   3. Submit. Verify redirect lands on /broker (broker not yet
 *      connected) — confirms the password cookie + CSRF + session
 *      registration all work cold.
 *   4. Pick "Alpaca Markets" from the broker dropdown, click
 *      "Connect Account".
 *   5. Verify the Alpaca callback redirects to /dashboard.
 *   6. Verify the PAPER pill is rendered (post-login state good).
 *   7. Place a paper LIMIT order via Search → Trade button to prove
 *      the full chain works after a cold login. Cancel for cleanup.
 *
 * Catches the kind of regression that wouldn't surface in the
 * normal suite: CSRF token issues, session cookie eviction on
 * redirect, capability store not refreshing after broker connect,
 * etc.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function loadDotenv(): Record<string, string> {
  const envPath = path.resolve(__dirname, '..', '..', '.env')
  const raw = fs.readFileSync(envPath, 'utf8')
  const out: Record<string, string> = {}
  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const eq = t.indexOf('=')
    if (eq === -1) continue
    const k = t.slice(0, eq).trim()
    let v = t.slice(eq + 1).trim()
    if ((v.startsWith("'") && v.endsWith("'")) || (v.startsWith('"') && v.endsWith('"'))) {
      v = v.slice(1, -1)
    }
    out[k] = v
  }
  return out
}

const ENV = loadDotenv()
const USERNAME = ENV.web_login_username || ''
const PASSWORD = ENV.web_login_password || ''
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000'

const SCREENSHOT_DIR = path.resolve(
  __dirname,
  '..',
  'test-results-live',
  'paper-trading-fresh-login',
)
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })

test.setTimeout(120_000)

test('fresh login → broker connect → dashboard → place order → cancel', async ({
  browser,
}) => {
  // CRITICAL: NO storageState — operator-of-record opens a fresh
  // browser. This test's value is exactly that nothing is shortcut.
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.log('[pageerror]', e.message))

  // ---- Step 1: cold load /login ---------------------------------------
  await page.goto(`${BASE}/login`)
  await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '01-login-page.png'),
    fullPage: true,
  })

  // Username + password inputs are id-keyed (shadcn Input).
  await page.locator('#username').fill(USERNAME)
  await page.locator('#password').fill(PASSWORD)
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '02-login-form-filled.png'),
    fullPage: true,
  })

  // ---- Step 2: submit, expect redirect ---------------------------------
  // The form posts to /auth/login. After success the React app
  // navigates to either /broker (no broker session yet) or
  // /dashboard (resume succeeded).
  const loginRespPromise = page.waitForResponse(
    (r) => r.url().includes('/auth/login') && r.request().method() === 'POST',
    { timeout: 10_000 },
  )
  await page.getByRole('button', { name: /sign in/i }).click()
  const loginResp = await loginRespPromise
  expect(loginResp.status(), `cold login failed: ${await loginResp.text()}`).toBe(
    200,
  )

  // Wait for the SPA to navigate. /broker OR /dashboard are both
  // legal landing states (resume vs fresh broker auth).
  await page.waitForURL(/\/(broker|dashboard)/, { timeout: 10_000 })
  await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => {})

  // ---- Step 3: connect Alpaca if we landed on /broker ------------------
  if (page.url().endsWith('/broker')) {
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '03-broker-select.png'),
      fullPage: true,
    })

    // The broker picker is a Radix Select — open the trigger, then
    // click the Alpaca item by accessible name.
    await page.locator('#broker-select').click()
    await page.getByRole('option', { name: /Alpaca Markets/i }).click()
    await page.getByRole('button', { name: /connect account/i }).click()

    // Connect Account submits to /alpaca/callback which 302s to
    // /dashboard on success.
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 })
  }

  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '04-dashboard-after-fresh-login.png'),
    fullPage: true,
  })

  // ---- Step 4: PAPER pill confirms broker-mode resolution worked ------
  await expect(
    page.getByTestId('broker-paper-pill'),
    'PAPER pill missing after fresh login',
  ).toBeVisible({ timeout: 5_000 })

  // ---- Step 5: end-to-end order placement ------------------------------
  await page.goto(`${BASE}/search?symbol=AAPL`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await expect(page.getByTestId('trade-AAPL-XNAS')).toBeVisible({ timeout: 15_000 })
  await page.getByTestId('trade-AAPL-XNAS').click()
  await expect(page.getByTestId('place-order-v2')).toBeVisible({ timeout: 10_000 })

  await page.getByTestId('v2-quantity').fill('1')
  await page.getByTestId('v2-order-type').selectOption('LIMIT')
  await page.getByTestId('v2-price').fill('50.00')

  // Generous timeout — under eventlet's cooperative scheduling,
  // the WSGI worker shares one OS thread with the trade-updates
  // stream + master-contract scheduler, so place-order latency is
  // higher than under the parallel Flask dev server. 30s is well
  // above the 99th percentile under eventlet load.
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/api/v2/orders') && r.request().method() === 'POST',
    { timeout: 30_000 },
  )
  await page.getByTestId('v2-submit').click()
  const resp = await respPromise
  const body = await resp.json()
  expect(resp.status(), `order place failed: ${JSON.stringify(body)}`).toBe(200)
  const orderId = body.data?.order_id as string
  expect(orderId).toBeTruthy()

  // ---- Cleanup --------------------------------------------------------
  const apiResp = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  const apikey = (await apiResp.json()).api_key as string
  await ctx.request.delete(`${BASE}/api/v2/orders/${orderId}`, {
    headers: { 'X-API-KEY': apikey },
  })

  await ctx.close()
})
