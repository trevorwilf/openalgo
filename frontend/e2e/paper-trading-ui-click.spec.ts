/**
 * Real DOM click-through against the live Flask instance.
 *
 * Drives the place-order flow end-to-end through the actual React
 * components: Search page → click "Trade" on AAPL row → fill the
 * PlaceOrderDialogV2 form → click submit → verify the order lands
 * via /api/v2/orders → cancel via API for cleanup.
 *
 * This catches problems no API-only test would find — wrong DOM
 * selectors, forms that don't submit, controls hidden behind feature
 * flags, capability mismatches between the v2 dialog and the broker
 * plugin.json.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { cancelAllAlpacaOpenOrders } from './alpaca-cleanup'

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
  'paper-trading-ui-click',
)
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })

let storageStateFile: string

test.describe.configure({ mode: 'serial' })
test.setTimeout(120_000)

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

// Cancel any leftover open orders so MARKET/STOP orders parked
// across previous specs don't trip Alpaca wash-trade prevention.
test.beforeEach(async () => {
  await cancelAllAlpacaOpenOrders()
})

test('Search → click Trade → place LIMIT order → verify in orderbook → cancel', async ({
  browser,
}) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const page = await ctx.newPage()

  // Navigate with ?symbol=AAPL so the search auto-runs.
  await page.goto(`${BASE}/search?symbol=AAPL`)
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})

  // Wait until at least one Trade button is rendered (search results
  // landed). Selector is stable: data-testid baked into the row.
  const tradeBtn = page.getByTestId('trade-AAPL-XNAS')
  await expect(tradeBtn).toBeVisible({ timeout: 15_000 })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '01-search-with-trade-button.png'),
    fullPage: true,
  })

  // Click Trade — opens the place-order dialog.
  await tradeBtn.click()
  const dialog = page.getByTestId('place-order-dialog')
  await expect(dialog).toBeVisible({ timeout: 5_000 })
  // Wait for the actual form to mount inside the dialog (it's gated
  // on capabilities + apikey + rules being loaded).
  const form = page.getByTestId('place-order-v2')
  await expect(form).toBeVisible({ timeout: 10_000 })
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '02-place-order-dialog-open.png'),
    fullPage: true,
  })

  // Drive the form via stable testids. PlaceOrderDialogV2 attaches
  // `data-testid="v2-{field}"` on every control specifically so e2e
  // tests aren't fragile to label/markup tweaks.
  await page.getByTestId('v2-side').selectOption('BUY')
  await page.getByTestId('v2-quantity').fill('1')
  await page.getByTestId('v2-order-type').selectOption('LIMIT')
  // The price input only renders for LIMIT-style order types — wait
  // for it to appear after the order_type change.
  const priceField = page.getByTestId('v2-price')
  await expect(priceField).toBeVisible({ timeout: 3_000 })
  await priceField.fill('50.00')
  await page.getByTestId('v2-tif').selectOption('DAY')
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '03-form-filled.png'),
    fullPage: true,
  })

  const submit = page.getByTestId('v2-submit')
  await expect(submit).toBeVisible({ timeout: 5_000 })

  // Capture the response so we can extract the order_id for cleanup
  // even if the dialog auto-closes.
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/api/v2/orders') && r.request().method() === 'POST',
    { timeout: 10_000 },
  )
  await submit.click()
  const resp = await respPromise
  expect(resp.status(), `place returned non-2xx: ${await resp.text()}`).toBeLessThan(300)
  const placeBody = await resp.json()
  const orderId = placeBody.data?.order_id
  expect(orderId, 'order_id missing from response').toBeTruthy()

  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '04-after-submit.png'),
    fullPage: true,
  })

  // Verify it shows up in /orderbook.
  await page.goto(`${BASE}/orderbook`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '05-orderbook-with-new-order.png'),
    fullPage: true,
  })
  // The order_id appears as a font-mono cell in the orderbook table.
  await expect(page.getByText(orderId)).toBeVisible({ timeout: 10_000 })

  // Cleanup — cancel the order via API.
  const apiResp = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  const apikey = (await apiResp.json()).api_key as string
  await ctx.request.delete(`${BASE}/api/v2/orders/${orderId}`, {
    headers: { 'X-API-KEY': apikey },
  })

  await ctx.close()
})
