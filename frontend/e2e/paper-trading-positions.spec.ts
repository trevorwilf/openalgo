/**
 * Verifies the /positions React page renders cleanly against the
 * v1 bridge's `/api/v1/positionbook` response shape for Alpaca.
 *
 * Cannot open a real position when the market is closed (Sunday →
 * Alpaca holds new orders in ACCEPTED forever), so this test asserts
 * the empty-state path:
 *
 *   * `/positions` returns HTTP 200
 *   * No 5xx network failures during render
 *   * `/api/v1/positionbook` returns the legacy `{status: "success",
 *     data: []}` envelope
 *   * Page DOM mounts (#root visible)
 *
 * A future "with-position" assertion can be layered on once the
 * market's open and a fillable order has executed.
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
  'paper-trading-positions',
)
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })

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
  storageStateFile = path.join(SCREENSHOT_DIR, 'auth-state.json')
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

test('/positions renders the empty state without 5xx', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const page = await ctx.newPage()
  const failures: { url: string; status: number }[] = []
  page.on('response', (r) => {
    if (r.status() >= 500) failures.push({ url: r.url(), status: r.status() })
  })

  const resp = await page.goto(`${BASE}/positions`)
  expect(resp?.status()).toBeLessThan(400)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'positions-empty.png'),
    fullPage: true,
  })

  await expect(page.locator('#root')).toBeVisible()
  expect(failures, `5xx on /positions: ${JSON.stringify(failures)}`).toEqual([])
  await ctx.close()
})

test('/holdings renders the empty state without 5xx', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const page = await ctx.newPage()
  const failures: { url: string; status: number }[] = []
  page.on('response', (r) => {
    if (r.status() >= 500) failures.push({ url: r.url(), status: r.status() })
  })

  const resp = await page.goto(`${BASE}/holdings`)
  expect(resp?.status()).toBeLessThan(400)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'holdings-empty.png'),
    fullPage: true,
  })

  await expect(page.locator('#root')).toBeVisible()
  expect(failures, `5xx on /holdings: ${JSON.stringify(failures)}`).toEqual([])
  await ctx.close()
})

test('/api/v1/positionbook + /api/v2/positions return well-formed empty responses', async ({
  browser,
}) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = (await (await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })).json()).api_key as string

  const v1 = await ctx.request.post(`${BASE}/api/v1/positionbook/`, {
    data: { apikey },
  })
  expect(v1.status()).toBe(200)
  const v1Body = await v1.json()
  expect(v1Body.status).toBe('success')
  expect(Array.isArray(v1Body.data)).toBe(true)

  const v2 = await ctx.request.get(`${BASE}/api/v2/positions`, {
    headers: { 'X-API-KEY': apikey },
  })
  expect(v2.status()).toBe(200)
  const v2Body = await v2.json()
  expect(v2Body.data).toBeTruthy()
  expect(Array.isArray(v2Body.data.positions)).toBe(true)

  await ctx.close()
})
