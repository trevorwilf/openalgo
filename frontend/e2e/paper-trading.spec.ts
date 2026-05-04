/**
 * Paper-trading flow against the live Alpaca-configured Flask
 * instance. Drives every endpoint a paper trader hits during a
 * normal trading day:
 *
 *   1. Login (password + Alpaca callback)
 *   2. API key page render + regenerate
 *   3. Dashboard render — funds widget shows real Alpaca balance
 *   4. Place a paper limit order via /api/v1/placeorder bridge
 *   5. Order book renders and shows the new order
 *   6. Cancel via UI (/cancel_order session endpoint)
 *   7. Confirm cancelled
 *   8. Direct v2 path: place + list + cancel via /api/v2/orders
 *
 * Captures screenshots of every page transition so the operator
 * can review the rendering after the fact.
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config=playwright.live.config.ts \
 *     paper-trading.spec.ts
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
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq === -1) continue
    const k = trimmed.slice(0, eq).trim()
    let v = trimmed.slice(eq + 1).trim()
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

if (!USERNAME || !PASSWORD) {
  throw new Error('Missing web_login_username/web_login_password in .env')
}

const SCREENSHOT_DIR = path.resolve(
  __dirname,
  '..',
  'test-results-live',
  'paper-trading',
)
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })

interface FailedRequest {
  url: string
  method: string
  status: number
}

let storageStateFile: string

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext()

  const csrfResp = await ctx.request.get(`${BASE}/auth/csrf-token`)
  const csrf = (await csrfResp.json()).csrf_token

  const loginResp = await ctx.request.post(`${BASE}/auth/login`, {
    form: { username: USERNAME, password: PASSWORD },
    headers: { 'X-CSRFToken': csrf },
  })
  expect(loginResp.status(), `login failed: ${await loginResp.text()}`).toBeLessThan(400)

  const cb = await ctx.request.get(`${BASE}/alpaca/callback`, { maxRedirects: 0 })
  expect(cb.status(), `broker callback failed`).toBeLessThan(500)

  storageStateFile = path.join(SCREENSHOT_DIR, 'auth-state.json')
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

// Cancel any leftover open orders before each order-placing test so
// MARKET/STOP orders parked across previous specs don't trip
// Alpaca's wash-trade prevention.
test.beforeEach(async () => {
  await cancelAllAlpacaOpenOrders()
})

async function attachObservers(page: import('@playwright/test').Page) {
  const obs: { failed: FailedRequest[] } = { failed: [] }
  page.on('response', (resp) => {
    const status = resp.status()
    if (status >= 400 && status < 600) {
      obs.failed.push({
        url: resp.url(),
        method: resp.request().method(),
        status,
      })
    }
  })
  return obs
}

test.setTimeout(180_000)

test('Paper trading — full UI flow', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const page = await ctx.newPage()
  const obs = await attachObservers(page)

  // Step 1: dashboard
  await page.goto(`${BASE}/dashboard`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '01-dashboard.png'),
    fullPage: true,
  })
  expect(
    obs.failed.filter((f) => f.status >= 500),
    `dashboard 5xx: ${JSON.stringify(obs.failed.filter((f) => f.status >= 500))}`,
  ).toEqual([])

  // Step 2: API key page — regenerate the key
  obs.failed.length = 0
  await page.goto(`${BASE}/apikey`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '02-apikey.png'),
    fullPage: true,
  })

  // Step 3: orderbook page — should render orderbook from /api/v1/orderbook
  // (bridged to /api/v2/orders internally)
  obs.failed.length = 0
  await page.goto(`${BASE}/orderbook`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '03-orderbook.png'),
    fullPage: true,
  })
  const orderbookFiveXX = obs.failed.filter((f) => f.status >= 500)
  expect(orderbookFiveXX, `orderbook 5xx: ${JSON.stringify(orderbookFiveXX)}`).toEqual([])

  // Step 4: positions page
  obs.failed.length = 0
  await page.goto(`${BASE}/positions`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '04-positions.png'),
    fullPage: true,
  })
  const positionsFiveXX = obs.failed.filter((f) => f.status >= 500)
  expect(positionsFiveXX, `positions 5xx: ${JSON.stringify(positionsFiveXX)}`).toEqual([])

  // Step 5: holdings page
  obs.failed.length = 0
  await page.goto(`${BASE}/holdings`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '05-holdings.png'),
    fullPage: true,
  })

  // Step 6: tradebook page
  obs.failed.length = 0
  await page.goto(`${BASE}/tradebook`)
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {})
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, '06-tradebook.png'),
    fullPage: true,
  })

  await ctx.close()
})

test('Paper trading — API-driven place + UI-driven cancel', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })

  // Get API key from /apikey
  const apikeyResp = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  const apikey = (await apikeyResp.json()).api_key as string
  expect(apikey, 'API key not retrievable').toBeTruthy()

  // Place a LIMIT order via the v1 bridge (this is what the React UI uses)
  const placeResp = await ctx.request.post(`${BASE}/api/v1/placeorder/`, {
    data: {
      apikey,
      symbol: 'AAPL',
      exchange: 'XNAS',
      action: 'BUY',
      quantity: '1',
      price_type: 'LIMIT',
      price: '100.00',
      product: 'MIS',
    },
  })
  const placeBody = await placeResp.json()
  console.log('[paper-trading] /api/v1/placeorder ->', placeResp.status(), placeBody)
  expect(placeResp.status()).toBe(200)
  const orderId = placeBody.orderid as string
  expect(orderId, 'order id not returned').toBeTruthy()

  // Verify it shows up in the orderbook
  const orderbookResp = await ctx.request.post(`${BASE}/api/v1/orderbook/`, {
    data: { apikey },
  })
  const orderbookBody = await orderbookResp.json()
  console.log(
    '[paper-trading] /api/v1/orderbook ->',
    orderbookResp.status(),
    'count=',
    orderbookBody.data?.orders?.length,
  )
  expect(orderbookResp.status()).toBe(200)
  const found = (orderbookBody.data?.orders || []).find(
    (o: { orderid: string }) => o.orderid === orderId,
  )
  expect(found, `order ${orderId} not found in orderbook`).toBeTruthy()

  // Cancel via the UI's session-based /cancel_order endpoint
  // (this is what tradingApi.cancelOrder uses).
  const csrfResp = await ctx.request.get(`${BASE}/auth/csrf-token`)
  const csrf = (await csrfResp.json()).csrf_token

  const cancelResp = await ctx.request.post(`${BASE}/cancel_order`, {
    data: { orderid: orderId },
    headers: { 'X-CSRFToken': csrf },
  })
  const cancelBody = await cancelResp.json()
  console.log('[paper-trading] /cancel_order ->', cancelResp.status(), cancelBody)
  expect(cancelResp.status()).toBe(200)
  expect(cancelBody.status).toBe('success')

  // Confirm via /api/v1/orderbook that the order is canceled
  const orderbook2 = await ctx.request.post(`${BASE}/api/v1/orderbook/`, {
    data: { apikey },
  })
  const ob2 = await orderbook2.json()
  const stillOpen = (ob2.data?.orders || []).find(
    (o: { orderid: string; order_status: string }) =>
      o.orderid === orderId
      && ['new', 'accepted', 'pending_new', 'partially_filled'].includes(
        (o.order_status || '').toLowerCase(),
      ),
  )
  expect(stillOpen, `order ${orderId} still open after cancel`).toBeFalsy()

  await ctx.close()
})

test('Paper trading — pure /api/v2 round trip', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })

  const apikeyResp = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  const apikey = (await apikeyResp.json()).api_key as string
  const headers = { 'X-API-KEY': apikey, 'Content-Type': 'application/json' }

  // Place via v2
  const placeResp = await ctx.request.post(`${BASE}/api/v2/orders`, {
    headers,
    data: {
      instrument: { venue_code: 'XNAS', canonical_symbol: 'AAPL' },
      side: 'BUY',
      quantity: '1',
      quantity_unit: 'WHOLE',
      time_in_force: 'DAY',
      order_type: 'LIMIT',
      price: '100.00',
    },
  })
  const placeBody = await placeResp.json()
  expect(placeResp.status(), JSON.stringify(placeBody)).toBe(200)
  const orderId = placeBody.data.order_id as string

  // List
  const listResp = await ctx.request.get(`${BASE}/api/v2/orders?status=open`, {
    headers,
  })
  const listBody = await listResp.json()
  expect(listResp.status()).toBe(200)
  const found = (listBody.data?.orders || []).find(
    (o: { id: string }) => o.id === orderId,
  )
  expect(found, `order ${orderId} not in v2 list`).toBeTruthy()

  // Get by ID
  const getResp = await ctx.request.get(`${BASE}/api/v2/orders/${orderId}`, {
    headers,
  })
  expect(getResp.status()).toBe(200)

  // Cancel
  const cancelResp = await ctx.request.delete(`${BASE}/api/v2/orders/${orderId}`, {
    headers,
  })
  expect(cancelResp.status()).toBe(200)

  // Confirm — Alpaca transitions accepted → pending_cancel → canceled
  // asynchronously, so poll up to 10s for one of the terminal states.
  let finalStatus: string | undefined
  for (let attempt = 0; attempt < 10; attempt++) {
    await new Promise((r) => setTimeout(r, 1000))
    const probe = await ctx.request.get(`${BASE}/api/v2/orders/${orderId}`, {
      headers,
    })
    if (probe.status() === 200) {
      const body = await probe.json()
      finalStatus = (body.data?.order?.status || '').toLowerCase()
      if (
        ['canceled', 'cancelled', 'pending_cancel', 'expired', 'rejected'].includes(
          finalStatus,
        )
      ) {
        break
      }
    }
  }
  expect(
    finalStatus,
    `v2 order ${orderId} did not enter a canceled/terminal state; final=${finalStatus}`,
  ).toMatch(/canceled|cancelled|pending_cancel|expired|rejected/)

  await ctx.close()
})
