/**
 * Verify the PAPER pill renders in the navbar after login.
 *
 * The pill is a critical safety affordance — operators should never
 * have to wonder which broker environment they're connected to.
 * This test asserts:
 *   1. /auth/broker-config returns ``broker_mode: "paper"`` (with
 *      the operator's PK paper key in BROKER_API_KEY).
 *   2. The Navbar renders ``data-testid="broker-paper-pill"``.
 *   3. The Navbar does NOT render the LIVE pill at the same time.
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

test.describe.configure({ mode: 'serial' })
test.setTimeout(60_000)

let storageStateFile: string

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext()
  const csrf = (await (await ctx.request.get(`${BASE}/auth/csrf-token`)).json()).csrf_token
  await ctx.request.post(`${BASE}/auth/login`, {
    form: { username: USERNAME, password: PASSWORD },
    headers: { 'X-CSRFToken': csrf },
  })
  await ctx.request.get(`${BASE}/alpaca/callback`, { maxRedirects: 0 })
  storageStateFile = path.resolve(
    __dirname,
    '..',
    'test-results-live',
    'paper-trading-mode-pill',
    'auth-state.json',
  )
  fs.mkdirSync(path.dirname(storageStateFile), { recursive: true })
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

test('/auth/broker-config returns broker_mode field', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const r = await ctx.request.get(`${BASE}/auth/broker-config`)
  expect(r.status()).toBe(200)
  const body = await r.json()
  expect(body.broker_name).toBe('alpaca')
  expect(['paper', 'live', 'unknown']).toContain(body.broker_mode)
  // Operator's .env has the PK paper key in BROKER_API_KEY without
  // ALPACA_LIVE_MODE set, so the resolver MUST classify as paper.
  expect(body.broker_mode).toBe('paper')
  await ctx.close()
})

test('Navbar renders the PAPER pill (not LIVE) for the paper Alpaca session', async ({
  browser,
}) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const page = await ctx.newPage()

  await page.goto(`${BASE}/dashboard`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})

  // Yellow PAPER pill must be visible.
  await expect(
    page.getByTestId('broker-paper-pill'),
    'PAPER pill missing from navbar',
  ).toBeVisible({ timeout: 5_000 })

  // LIVE pill must NOT be present — having both at the same time
  // would be a confusing safety regression.
  await expect(
    page.getByTestId('broker-live-pill'),
    'LIVE pill rendered alongside PAPER (resolver bug)',
  ).toHaveCount(0)

  // Visual confirmation for the operator.
  const screenshotDir = path.resolve(
    __dirname,
    '..',
    'test-results-live',
    'paper-trading-mode-pill',
  )
  fs.mkdirSync(screenshotDir, { recursive: true })
  await page.screenshot({
    path: path.join(screenshotDir, 'navbar-with-paper-pill.png'),
    fullPage: false,
  })

  await ctx.close()
})
