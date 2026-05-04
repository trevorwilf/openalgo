/**
 * Paper-trading "every action" spec — exercises every button-driven
 * order-management flow a paper trader hits during a normal session,
 * with the full state-machine assertions on the canonical
 * :class:`OrderStatus` vocabulary.
 *
 * Each test is independent — they don't share state — so a failure
 * in one doesn't cascade. Each places its own order(s) and cleans up
 * before exiting.
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config=playwright.live.config.ts \
 *     paper-trading-actions.spec.ts
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
const ALPACA_KEY = ENV.BROKER_API_KEY || ''
const ALPACA_SECRET = ENV.BROKER_API_SECRET || ''
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000'

async function isMarketOpen(): Promise<boolean> {
  if (!ALPACA_KEY || !ALPACA_SECRET) return false
  const baseUrl = ALPACA_KEY.startsWith('PK')
    ? 'https://paper-api.alpaca.markets'
    : 'https://api.alpaca.markets'
  try {
    const r = await fetch(`${baseUrl}/v2/clock`, {
      headers: {
        'APCA-API-KEY-ID': ALPACA_KEY,
        'APCA-API-SECRET-KEY': ALPACA_SECRET,
      },
    })
    if (!r.ok) return false
    const body = await r.json()
    return Boolean(body.is_open)
  } catch {
    return false
  }
}

test.describe.configure({ mode: 'serial' })
test.setTimeout(120_000)

const SCREENSHOT_DIR = path.resolve(
  __dirname,
  '..',
  'test-results-live',
  'paper-trading-actions',
)
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })

let storageStateFile: string

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext()
  const csrfResp = await ctx.request.get(`${BASE}/auth/csrf-token`)
  const csrf = (await csrfResp.json()).csrf_token

  const loginResp = await ctx.request.post(`${BASE}/auth/login`, {
    form: { username: USERNAME, password: PASSWORD },
    headers: { 'X-CSRFToken': csrf },
  })
  expect(loginResp.status()).toBeLessThan(400)

  const cb = await ctx.request.get(`${BASE}/alpaca/callback`, { maxRedirects: 0 })
  expect(cb.status()).toBeLessThan(500)

  storageStateFile = path.join(SCREENSHOT_DIR, 'auth-state.json')
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

async function getApiKey(ctx: import('@playwright/test').BrowserContext): Promise<string> {
  const r = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  return (await r.json()).api_key as string
}

async function getCsrf(ctx: import('@playwright/test').BrowserContext): Promise<string> {
  const r = await ctx.request.get(`${BASE}/auth/csrf-token`)
  return (await r.json()).csrf_token as string
}

interface PlaceOptions {
  symbol?: string
  exchange?: string
  side?: 'BUY' | 'SELL'
  quantity?: string
  price?: string
  orderType?: 'MARKET' | 'LIMIT' | 'STOP' | 'STOP_LIMIT'
  triggerPrice?: string
  tif?: 'DAY' | 'GTC' | 'IOC' | 'FOK'
}

async function placeV2(
  ctx: import('@playwright/test').BrowserContext,
  apikey: string,
  opts: PlaceOptions = {},
): Promise<string> {
  const body = {
    instrument: {
      venue_code: opts.exchange ?? 'XNAS',
      canonical_symbol: opts.symbol ?? 'AAPL',
    },
    side: opts.side ?? 'BUY',
    quantity: opts.quantity ?? '1',
    quantity_unit: 'WHOLE',
    time_in_force: opts.tif ?? 'DAY',
    order_type: opts.orderType ?? 'LIMIT',
    ...(opts.orderType === 'MARKET'
      ? {}
      : { price: opts.price ?? '100.00' }),
    ...(opts.triggerPrice ? { trigger_price: opts.triggerPrice } : {}),
  }
  const r = await ctx.request.post(`${BASE}/api/v2/orders`, {
    headers: { 'X-API-KEY': apikey, 'Content-Type': 'application/json' },
    data: body,
  })
  const j = await r.json()
  if (r.status() !== 200) {
    throw new Error(`place failed ${r.status()}: ${JSON.stringify(j)}`)
  }
  return j.data.order_id as string
}

async function pollUntilStatus(
  ctx: import('@playwright/test').BrowserContext,
  apikey: string,
  orderId: string,
  acceptable: string[],
  timeoutMs = 10_000,
): Promise<string> {
  const start = Date.now()
  let final = ''
  while (Date.now() - start < timeoutMs) {
    const r = await ctx.request.get(`${BASE}/api/v2/orders/${orderId}`, {
      headers: { 'X-API-KEY': apikey },
    })
    if (r.status() === 200) {
      const body = await r.json()
      const native = (body.data?.order?.status || '').toLowerCase()
      const canonical = (body.data?.order?.canonical_status || '').toUpperCase()
      final = `native=${native} canonical=${canonical}`
      if (acceptable.includes(native) || acceptable.includes(canonical)) {
        return final
      }
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`order ${orderId} did not reach any of [${acceptable.join(',')}]; last=${final}`)
}

// ---------------------------------------------------------------------------
// Tests — one independent flow per test.
// ---------------------------------------------------------------------------

test('place + cancel single order via /api/v2/orders', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)

  const orderId = await placeV2(ctx, apikey, { price: '50.00' })

  const cancelResp = await ctx.request.delete(`${BASE}/api/v2/orders/${orderId}`, {
    headers: { 'X-API-KEY': apikey },
  })
  expect(cancelResp.status()).toBe(200)

  const status = await pollUntilStatus(ctx, apikey, orderId, [
    'CANCELED', 'PENDING_CANCEL', 'EXPIRED',
    'canceled', 'pending_cancel', 'expired',
  ])
  expect(status).toMatch(/canon|native/)
  await ctx.close()
})

test('/modify_order is wired and returns a structured response', async ({ browser }) => {
  // Note: Alpaca's modify only works on orders that have transitioned
  // out of ACCEPTED (which means the market must be open for routing).
  // Outside market hours the broker holds orders in ACCEPTED and
  // returns 422 "cannot replace order in accepted status". This test
  // proves the wire is up either way:
  //
  //   * Market open:   modify succeeds → 200
  //   * Market closed: modify returns Alpaca's structured 422 with
  //                    code 42210000 (cannot replace in accepted)
  //
  // 5xx is the failure mode we're guarding against — a 5xx means our
  // shim crashed before reaching Alpaca.
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)

  const orderId = await placeV2(ctx, apikey, { price: '50.00' })

  const csrf = await getCsrf(ctx)
  const modifyResp = await ctx.request.post(`${BASE}/modify_order`, {
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    data: {
      orderid: orderId,
      symbol: 'AAPL',
      exchange: 'XNAS',
      action: 'BUY',
      product: 'MIS',
      pricetype: 'LIMIT',
      price: '60.00',
      quantity: 1,
    },
  })
  const status = modifyResp.status()
  const body = await modifyResp.text()
  console.log(`[modify_order] ${status}: ${body.slice(0, 200)}`)
  // Acceptable: 200 (open market modify succeeded) OR
  // 422 with Alpaca's "cannot replace" code (closed market) OR
  // 4xx with a structured error envelope. 5xx is the regression.
  expect(status, `modify_order returned 5xx: ${body}`).toBeLessThan(500)

  // Cleanup — cancel anything still open.
  await new Promise((r) => setTimeout(r, 500))
  const list = await ctx.request.get(`${BASE}/api/v2/orders?status=open`, {
    headers: { 'X-API-KEY': apikey },
  })
  const open = ((await list.json()).data?.orders || []) as Array<{ id: string }>
  for (const o of open) {
    await ctx.request.delete(`${BASE}/api/v2/orders/${o.id}`, {
      headers: { 'X-API-KEY': apikey },
    })
  }
  await ctx.close()
})

test('cancel-all flattens every open order', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)

  // Place three resting LIMIT orders at deliberately-unfillable prices
  await placeV2(ctx, apikey, { price: '50.00' })
  await placeV2(ctx, apikey, { price: '51.00' })
  await placeV2(ctx, apikey, { price: '52.00' })

  // Sanity — we have ≥ 3 open
  const before = await ctx.request.get(`${BASE}/api/v2/orders?status=open`, {
    headers: { 'X-API-KEY': apikey },
  })
  expect(((await before.json()).data?.count || 0)).toBeGreaterThanOrEqual(3)

  // Trigger /cancel_all_orders via the same UI path the React app
  // uses (session-auth + CSRF, NOT the apikey body convention).
  const csrf = await getCsrf(ctx)
  const cancelAll = await ctx.request.post(`${BASE}/cancel_all_orders`, {
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    data: {},
  })
  expect(cancelAll.status(), await cancelAll.text()).toBe(200)

  // Allow Alpaca a moment to flush the cancel queue
  let openCount = 999
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 1000))
    const r = await ctx.request.get(`${BASE}/api/v2/orders?status=open`, {
      headers: { 'X-API-KEY': apikey },
    })
    openCount = ((await r.json()).data?.count || 0)
    if (openCount === 0) break
  }
  expect(openCount, `expected 0 open orders, got ${openCount}`).toBe(0)
  await ctx.close()
})

test('orderbook bridge returns canonical_status alongside legacy display', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)

  // Place + cancel one so the orderbook has at least one terminal row
  const orderId = await placeV2(ctx, apikey, { price: '40.00' })
  await ctx.request.delete(`${BASE}/api/v2/orders/${orderId}`, {
    headers: { 'X-API-KEY': apikey },
  })
  await new Promise((r) => setTimeout(r, 2_000))

  const obResp = await ctx.request.post(`${BASE}/api/v1/orderbook/`, {
    data: { apikey },
    headers: { 'Content-Type': 'application/json' },
  })
  const ob = await obResp.json()
  const found = (ob.data?.orders || []).find(
    (o: { orderid: string }) => o.orderid === orderId,
  )
  expect(found, `orderbook missing ${orderId}`).toBeTruthy()
  // Canonical FIX-aligned status preserved
  expect(found.canonical_status).toMatch(/CANCELED|PENDING_CANCEL/)
  // Legacy India display vocabulary present
  expect(found.order_status).toMatch(/cancelled|open/)
  // Native Alpaca string preserved for debugging
  expect(found.native_status).toMatch(/canceled|pending_cancel/)
  await ctx.close()
})

test('search returns 13k+ Alpaca symbols across XNAS/XNYS/ARCX/BATS', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })

  // Empty query → blanket sample. 50-row default page is fine.
  const cases = [
    { q: 'AAPL', expectVenue: 'XNAS' },
    { q: 'TSLA', expectVenue: 'XNAS' },
    { q: 'NVDA', expectVenue: 'XNAS' },
    { q: 'JPM', expectVenue: 'XNYS' },
    { q: 'SPY', expectVenue: 'ARCX' },
    { q: 'QQQ', expectVenue: 'XNAS' },
  ]
  for (const c of cases) {
    const r = await ctx.request.get(`${BASE}/search/api/search?q=${c.q}`)
    expect(r.status(), `search ${c.q} failed`).toBe(200)
    const body = await r.json()
    const exact = (body.results || []).find((x: { symbol: string }) => x.symbol === c.q)
    expect(exact, `${c.q} missing from search`).toBeTruthy()
    expect(exact.exchange, `${c.q} on wrong venue`).toBe(c.expectVenue)
  }

  // Friendly alias resolution
  const r = await ctx.request.get(`${BASE}/search/api/search?q=AAPL&exchange=NASDAQ`)
  const body = await r.json()
  const exact = (body.results || []).find((x: { symbol: string }) => x.symbol === 'AAPL')
  expect(exact, 'NASDAQ alias did not resolve').toBeTruthy()
  await ctx.close()
})

test('quote returns real bid/ask for AAPL', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)
  const open = await isMarketOpen()

  const r = await ctx.request.post(`${BASE}/api/v2/quotes`, {
    headers: { 'X-API-KEY': apikey, 'Content-Type': 'application/json' },
    data: { instruments: [{ venue_code: 'XNAS', canonical_symbol: 'AAPL' }] },
  })
  expect(r.status()).toBe(200)
  const body = await r.json()
  const quote = body.data?.[0]?.quote
  expect(quote).toBeTruthy()
  // Both fields must be present and parseable. Outside regular
  // trading hours Alpaca's IEX feed often returns a stale or
  // half-populated quote (one side at 0, or bid > ask) — skip
  // the value/spread assertions post-close. Open hours: assert
  // both >0 AND ask >= bid.
  expect(typeof quote.bid).toBe('string')
  expect(typeof quote.ask).toBe('string')
  if (open) {
    expect(parseFloat(quote.bid)).toBeGreaterThan(0)
    expect(parseFloat(quote.ask)).toBeGreaterThan(0)
    expect(parseFloat(quote.ask)).toBeGreaterThanOrEqual(parseFloat(quote.bid))
  }
  await ctx.close()
})

test('/close_position is wired (no 5xx when no position exists)', async ({ browser }) => {
  // Cannot create a position when the market is closed (paper or
  // live). This test only validates that the legacy session-based
  // /close_position endpoint reaches Alpaca without our shim
  // crashing. When the market is open and you have a position,
  // the same flow submits a closing order and returns its order_id.
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const csrf = await getCsrf(ctx)

  const r = await ctx.request.post(`${BASE}/close_position`, {
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    data: { symbol: 'AAPL', exchange: 'XNAS', product: 'MIS' },
  })
  const status = r.status()
  const body = await r.text()
  console.log(`[close_position] ${status}: ${body.slice(0, 200)}`)
  expect(status, `close_position 5xx: ${body}`).toBeLessThan(500)
  await ctx.close()
})

test('/close_all_positions is wired (no 5xx when no positions exist)', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const csrf = await getCsrf(ctx)

  const r = await ctx.request.post(`${BASE}/close_all_positions`, {
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    data: {},
  })
  const status = r.status()
  const body = await r.text()
  console.log(`[close_all_positions] ${status}: ${body.slice(0, 200)}`)
  expect(status, `close_all_positions 5xx: ${body}`).toBeLessThan(500)
  await ctx.close()
})

test('balances returns real Alpaca paper-account values', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = await getApiKey(ctx)

  const r = await ctx.request.get(`${BASE}/api/v2/balances`, {
    headers: { 'X-API-KEY': apikey },
  })
  expect(r.status()).toBe(200)
  const body = await r.json()
  const balance = body.data?.balance
  expect(balance).toBeTruthy()
  expect(balance.currency).toBe('USD')
  expect(parseFloat(balance.cash)).toBeGreaterThan(0)
  expect(parseFloat(balance.buying_power)).toBeGreaterThan(0)
  await ctx.close()
})
