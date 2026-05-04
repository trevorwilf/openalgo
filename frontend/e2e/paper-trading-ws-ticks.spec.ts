/**
 * Verifies live market-data ticks flow from the operator's broker
 * (paper Alpaca) through the unified WebSocket proxy to the
 * BROWSER-side WebSocket client. Proves end-to-end:
 *   - Browser → ws://127.0.0.1:8765 (CORS / origin / auth path)
 *   - Server → broker adapter (alpaca_websocket.py auth + sub)
 *   - Broker → server → browser (publish topic → client routing)
 *
 * Skipped silently when the market is closed (Alpaca's
 * /v2/clock returns is_open=false). When market is open, AAPL
 * MUST produce at least 1 tick within 30s.
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
const WS_URL = process.env.OPENALGO_WS_URL || 'ws://127.0.0.1:8765'

test.describe.configure({ mode: 'serial' })
test.setTimeout(90_000)

async function isMarketOpen(): Promise<boolean> {
  if (!ALPACA_KEY || !ALPACA_SECRET) return false
  const base = ALPACA_KEY.startsWith('PK')
    ? 'https://paper-api.alpaca.markets'
    : 'https://api.alpaca.markets'
  try {
    const r = await fetch(`${base}/v2/clock`, {
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

test('Browser WebSocket subscribes to AAPL and receives live ticks', async ({
  browser,
}) => {
  const open = await isMarketOpen()
  test.skip(!open, 'market closed — Alpaca clock.is_open=false')

  const ctx = await browser.newContext()
  // Cold-login flow: get csrf, post login, then navigate.
  const csrf = (await (await ctx.request.get(`${BASE}/auth/csrf-token`)).json())
    .csrf_token
  await ctx.request.post(`${BASE}/auth/login`, {
    form: { username: USERNAME, password: PASSWORD },
    headers: { 'X-CSRFToken': csrf },
  })
  await ctx.request.get(`${BASE}/alpaca/callback`, { maxRedirects: 0 })

  const apikey = ((await (
    await ctx.request.get(`${BASE}/apikey`, {
      headers: { Accept: 'application/json' },
    })
  ).json()) as { api_key?: string }).api_key

  expect(apikey, 'apikey should be returned by /apikey').toBeTruthy()

  const page = await ctx.newPage()
  // Navigate to dashboard so the page has the cookie + can open
  // a browser-context WebSocket.
  await page.goto(`${BASE}/dashboard`)
  await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => {})

  // Run the WebSocket dance from inside the browser. Returns the
  // tick count + first tick payload so the test can assert.
  const result = await page.evaluate(
    async ({ wsUrl, apikey }) => {
      return await new Promise<{
        ticks: number
        firstTick: unknown
        authResp: string
        subResp: string
      }>((resolve, reject) => {
        const ws = new WebSocket(wsUrl)
        let ticks = 0
        let firstTick: unknown = null
        let authResp = ''
        let subResp = ''
        const timeout = setTimeout(() => {
          try {
            ws.close()
          } catch {}
          resolve({ ticks, firstTick, authResp, subResp })
        }, 30_000)

        ws.onopen = () => {
          ws.send(JSON.stringify({ action: 'authenticate', api_key: apikey }))
        }
        ws.onmessage = (event) => {
          const body = JSON.parse(event.data)
          if (!authResp && (body.status === 'success' || body.message?.match(/auth/i))) {
            authResp = String(body.message || body.status || '')
            ws.send(
              JSON.stringify({
                action: 'subscribe',
                symbol: 'AAPL',
                exchange: 'XNAS',
                mode: 'LTP',
              }),
            )
            return
          }
          if (!subResp && body.type === 'subscribe') {
            subResp = JSON.stringify(body.subscriptions || [])
            return
          }
          // Anything else is a tick.
          if (body.type === 'market_data' || body.data) {
            ticks += 1
            if (firstTick === null) firstTick = body
            if (ticks >= 2) {
              clearTimeout(timeout)
              try {
                ws.send(
                  JSON.stringify({
                    action: 'unsubscribe',
                    symbol: 'AAPL',
                    exchange: 'XNAS',
                    mode: 'LTP',
                  }),
                )
                ws.close()
              } catch {}
              resolve({ ticks, firstTick, authResp, subResp })
            }
          }
        }
        ws.onerror = (err) => {
          clearTimeout(timeout)
          reject(err)
        }
      })
    },
    { wsUrl: WS_URL, apikey: apikey! },
  )

  console.log('[ws-ticks] auth:', result.authResp)
  console.log('[ws-ticks] subscribe:', result.subResp)
  console.log('[ws-ticks] ticks received:', result.ticks)
  console.log('[ws-ticks] first tick:', JSON.stringify(result.firstTick).slice(0, 200))
  expect(result.ticks).toBeGreaterThan(0)

  await ctx.close()
})
