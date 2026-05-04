/**
 * Shared helper — cancel all open orders on the Alpaca paper account.
 *
 * Used by ``test.beforeEach`` in spec files that place orders, to
 * keep tests independent of each other.
 *
 * Background: Alpaca's wash-trade prevention rejects ``BUY @ $X LIMIT``
 * orders with ``code=40310000 / 403`` when an opposite-side
 * MARKET/STOP order is parked. When the market is closed, MARKET
 * orders sit in ``accepted`` state until the open, so any test that
 * places a MARKET SELL (e.g. ``close_position``) leaves a parked
 * order that trips wash detection on the next BUY-side test.
 *
 * This helper is invoked from spec ``beforeEach`` hooks rather than
 * the global setup so that tests stay independent — running a single
 * test with ``--grep`` still gets a clean slate.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let envLoaded = false

function loadEnvOnce(): void {
  if (envLoaded) return
  envLoaded = true
  const envPath = path.resolve(__dirname, '..', '..', '.env')
  if (!fs.existsSync(envPath)) return
  const text = fs.readFileSync(envPath, 'utf8')
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 0) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (
      (value.startsWith("'") && value.endsWith("'")) ||
      (value.startsWith('"') && value.endsWith('"'))
    ) {
      value = value.slice(1, -1)
    }
    if (!(key in process.env)) {
      process.env[key] = value
    }
  }
}

function alpacaCredentials(): { base: string; key: string; secret: string } | null {
  loadEnvOnce()
  const apiKey = process.env.BROKER_API_KEY || process.env.ALPACA_API_KEY || ''
  const apiSecret =
    process.env.BROKER_API_SECRET || process.env.ALPACA_API_SECRET || ''
  if (!apiKey || !apiSecret) return null
  const base = apiKey.startsWith('PK')
    ? 'https://paper-api.alpaca.markets'
    : 'https://api.alpaca.markets'
  return { base, key: apiKey, secret: apiSecret }
}

/** Cancel every open order on the Alpaca paper account. Idempotent. */
export async function cancelAllAlpacaOpenOrders(): Promise<number> {
  const creds = alpacaCredentials()
  if (!creds) return 0
  const headers = {
    'APCA-API-KEY-ID': creds.key,
    'APCA-API-SECRET-KEY': creds.secret,
  }
  try {
    const list = await fetch(`${creds.base}/v2/orders?status=open&limit=500`, {
      headers,
    })
    if (!list.ok) return 0
    const orders = (await list.json()) as Array<unknown>
    if (!Array.isArray(orders) || orders.length === 0) return 0
    const cancel = await fetch(`${creds.base}/v2/orders`, {
      method: 'DELETE',
      headers,
    })
    return cancel.status >= 200 && cancel.status < 300 ? orders.length : 0
  } catch {
    return 0
  }
}
