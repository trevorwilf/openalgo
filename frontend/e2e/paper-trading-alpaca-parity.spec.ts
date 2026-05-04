/**
 * Parity check between OpenAlgo's v1 bridge / v2 dispatcher and
 * Alpaca's direct REST API.
 *
 * The point: prove that when an operator places an order via the
 * OpenAlgo UI / API, the resulting order on Alpaca's side is
 * **shape-identical** to what they'd get from a direct
 * ``POST https://paper-api.alpaca.markets/v2/orders`` call.
 *
 * For each test:
 *  1. Place order A via OpenAlgo (`/api/v1/placeorder` or
 *     `/api/v2/orders`).
 *  2. Place order B via direct Alpaca with the same logical payload.
 *  3. Fetch both orders from Alpaca and compare the fields a paper
 *     trader actually cares about: symbol, side, qty, type,
 *     limit_price, time_in_force, extended_hours, order_class.
 *  4. Cancel both for cleanup.
 *
 * Reads paper API keys from .env. Direct Alpaca calls only ever use
 * the paper key (`BROKER_API_KEY` — starts with PK).
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { cancelAllAlpacaOpenOrders } from './alpaca-cleanup.ts'

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
const ALPACA_BASE = 'https://paper-api.alpaca.markets'

if (!ALPACA_KEY || !ALPACA_SECRET) {
  throw new Error('BROKER_API_KEY/BROKER_API_SECRET missing from .env')
}

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
    'paper-trading-alpaca-parity',
    'auth-state.json',
  )
  fs.mkdirSync(path.dirname(storageStateFile), { recursive: true })
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

// Cancel any leftover open orders on the paper account before every
// test. When the market is closed, MARKET/STOP orders parked by
// previous tests trip Alpaca's wash-trade prevention on the next BUY,
// surfacing as 403 ``code=40310000`` from the v1/v2 place endpoints.
test.beforeEach(async () => {
  await cancelAllAlpacaOpenOrders()
})

const ALPACA_HEADERS = {
  'APCA-API-KEY-ID': ALPACA_KEY,
  'APCA-API-SECRET-KEY': ALPACA_SECRET,
  'Content-Type': 'application/json',
}

interface AlpacaOrder {
  id: string
  symbol: string
  side: string
  qty: string | null
  notional: string | null
  type: string
  limit_price: string | null
  stop_price: string | null
  time_in_force: string
  extended_hours: boolean
  order_class: string
  status: string
}

async function placeDirectAlpaca(body: Record<string, unknown>): Promise<AlpacaOrder> {
  const r = await fetch(`${ALPACA_BASE}/v2/orders`, {
    method: 'POST',
    headers: ALPACA_HEADERS,
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`alpaca direct failed: ${r.status} ${await r.text()}`)
  return (await r.json()) as AlpacaOrder
}

async function fetchAlpaca(orderId: string): Promise<AlpacaOrder> {
  const r = await fetch(`${ALPACA_BASE}/v2/orders/${orderId}`, {
    headers: ALPACA_HEADERS,
  })
  if (!r.ok) throw new Error(`alpaca fetch failed: ${r.status}`)
  return (await r.json()) as AlpacaOrder
}

async function cancelAlpaca(orderId: string): Promise<void> {
  await fetch(`${ALPACA_BASE}/v2/orders/${orderId}`, {
    method: 'DELETE',
    headers: ALPACA_HEADERS,
  })
}

function compare(a: AlpacaOrder, b: AlpacaOrder, fields: (keyof AlpacaOrder)[]): void {
  for (const f of fields) {
    expect(
      a[f],
      `field ${String(f)} differs: openalgo=${JSON.stringify(a[f])} direct=${JSON.stringify(b[f])}`,
    ).toEqual(b[f])
  }
}

// ---------------------------------------------------------------------------
// Tests — each places one OpenAlgo order + one direct order, asserts
// the resulting Alpaca-side shapes match, then cleans up both.
// ---------------------------------------------------------------------------

test('parity: simple LIMIT order — bridge ≡ direct', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = (await (await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })).json()).api_key as string

  // OpenAlgo path — through the v1 bridge (what the React UI uses).
  const oaResp = await ctx.request.post(`${BASE}/api/v1/placeorder/`, {
    data: {
      apikey,
      symbol: 'AAPL',
      exchange: 'XNAS',
      action: 'BUY',
      quantity: '1',
      price_type: 'LIMIT',
      price: '50.00',
      product: 'MIS',
    },
  })
  const oaBody = await oaResp.json()
  const oaOrderId = oaBody.orderid as string
  expect(oaOrderId).toBeTruthy()

  // Direct Alpaca path — same logical order.
  const direct = await placeDirectAlpaca({
    symbol: 'AAPL',
    qty: '1',
    side: 'buy',
    type: 'limit',
    limit_price: '50.00',
    time_in_force: 'day',
  })

  // Wait briefly so both orders settle on Alpaca's side.
  await new Promise((r) => setTimeout(r, 500))
  const oaAlp = await fetchAlpaca(oaOrderId)
  const dirAlp = await fetchAlpaca(direct.id)

  compare(oaAlp, dirAlp, [
    'symbol',
    'side',
    'qty',
    'type',
    'limit_price',
    'time_in_force',
    'extended_hours',
    'order_class',
  ])

  await cancelAlpaca(oaOrderId)
  await cancelAlpaca(direct.id)
  await ctx.close()
})

test('parity: extended-hours LIMIT — bridge ≡ direct', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = (await (await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })).json()).api_key as string

  const oaResp = await ctx.request.post(`${BASE}/api/v1/placeorder/`, {
    data: {
      apikey,
      symbol: 'AAPL',
      exchange: 'XNAS',
      action: 'BUY',
      quantity: '1',
      price_type: 'LIMIT',
      price: '50.00',
      product: 'MIS',
      extended_hours: 'true',
    },
  })
  const oaOrderId = (await oaResp.json()).orderid as string

  const direct = await placeDirectAlpaca({
    symbol: 'AAPL',
    qty: '1',
    side: 'buy',
    type: 'limit',
    limit_price: '50.00',
    time_in_force: 'day',
    extended_hours: true,
  })

  await new Promise((r) => setTimeout(r, 500))
  const oaAlp = await fetchAlpaca(oaOrderId)
  const dirAlp = await fetchAlpaca(direct.id)

  expect(oaAlp.extended_hours).toBe(true)
  expect(dirAlp.extended_hours).toBe(true)
  compare(oaAlp, dirAlp, [
    'symbol', 'side', 'qty', 'type', 'limit_price',
    'time_in_force', 'extended_hours', 'order_class',
  ])

  await cancelAlpaca(oaOrderId)
  await cancelAlpaca(direct.id)
  await ctx.close()
})

test('parity: notional order — bridge ≡ direct', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = (await (await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })).json()).api_key as string

  // Notional = "buy $100 of AAPL". Alpaca only accepts notional with
  // MARKET (or DAY/GTC) so the simplest direct call is symmetric.
  const oaResp = await ctx.request.post(`${BASE}/api/v1/placeorder/`, {
    data: {
      apikey,
      symbol: 'AAPL',
      exchange: 'XNAS',
      action: 'BUY',
      quantity: '100',
      price_type: 'MARKET',
      product: 'MIS',
      notional: 'true',
    },
  })
  const oaOrderId = (await oaResp.json()).orderid as string

  const direct = await placeDirectAlpaca({
    symbol: 'AAPL',
    notional: '100',
    side: 'buy',
    type: 'market',
    time_in_force: 'day',
  })

  await new Promise((r) => setTimeout(r, 500))
  const oaAlp = await fetchAlpaca(oaOrderId)
  const dirAlp = await fetchAlpaca(direct.id)

  // Notional orders carry `notional` instead of `qty`. Both should be
  // null for `qty` and identical strings for `notional`.
  expect(oaAlp.notional).toBeTruthy()
  expect(dirAlp.notional).toBeTruthy()
  compare(oaAlp, dirAlp, [
    'symbol', 'side', 'type', 'notional',
    'time_in_force', 'extended_hours', 'order_class',
  ])

  await cancelAlpaca(oaOrderId)
  await cancelAlpaca(direct.id)
  await ctx.close()
})

test('parity: BRACKET via /api/v2/orders/combo ≡ direct order_class=bracket', async ({
  browser,
}) => {
  const ctx = await browser.newContext({ storageState: storageStateFile })
  const apikey = (await (await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })).json()).api_key as string

  const oaResp = await ctx.request.post(`${BASE}/api/v2/orders/combo`, {
    headers: { 'X-API-KEY': apikey, 'Content-Type': 'application/json' },
    data: {
      combo_type: 'BRACKET',
      time_in_force: 'DAY',
      session: 'REGULAR',
      legs: [
        {
          instrument_ref: { venue_code: 'XNAS', canonical_symbol: 'AAPL' },
          side: 'BUY',
          quantity: '1',
          quantity_unit: 'WHOLE',
          order_type: 'LIMIT',
          price: '50.00',
        },
        {
          instrument_ref: { venue_code: 'XNAS', canonical_symbol: 'AAPL' },
          side: 'SELL',
          quantity: '1',
          quantity_unit: 'WHOLE',
          order_type: 'LIMIT',
          price: '400.00',
        },
        {
          instrument_ref: { venue_code: 'XNAS', canonical_symbol: 'AAPL' },
          side: 'SELL',
          quantity: '1',
          quantity_unit: 'WHOLE',
          order_type: 'STOP',
          trigger_price: '30.00',
        },
      ],
    },
  })
  const oaBody = await oaResp.json()
  expect(oaResp.status(), JSON.stringify(oaBody)).toBe(200)
  const oaParentId = oaBody.data?.native_response?.id as string
  expect(oaParentId).toBeTruthy()

  const direct = await placeDirectAlpaca({
    symbol: 'AAPL',
    qty: '1',
    side: 'buy',
    type: 'limit',
    limit_price: '50.00',
    time_in_force: 'day',
    order_class: 'bracket',
    take_profit: { limit_price: '400.00' },
    stop_loss: { stop_price: '30.00' },
  })

  await new Promise((r) => setTimeout(r, 500))
  const oaAlp = await fetchAlpaca(oaParentId)
  const dirAlp = await fetchAlpaca(direct.id)

  expect(oaAlp.order_class).toBe('bracket')
  expect(dirAlp.order_class).toBe('bracket')
  compare(oaAlp, dirAlp, [
    'symbol', 'side', 'qty', 'type', 'limit_price',
    'time_in_force', 'order_class',
  ])

  await cancelAlpaca(oaParentId)
  await cancelAlpaca(direct.id)
  await ctx.close()
})
