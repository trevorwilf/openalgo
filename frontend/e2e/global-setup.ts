/**
 * Playwright global setup — runs once before any test in the suite.
 *
 * Cancels any open orders on the Alpaca paper account so that
 * leftover state from a previous run does not trip wash-trade
 * prevention on the first test that places a deep-OOM LIMIT BUY.
 *
 * Symptom this prevents: Alpaca returns ``code=40310000 / 403`` with
 * ``"potential wash trade detected. use complex orders"`` and
 * ``"reject_reason":"opposite side market/stop order exists"`` when
 * a SELL MARKET / STOP order is parked from a prior bracket-test or
 * close-position leg, and the next test tries a BUY @ $50 LIMIT.
 *
 * The .env file is loaded by Flask, but Playwright's Node runtime
 * does not auto-load it. We read it manually so this hook works
 * standalone (no need for the operator to export ALPACA env vars in
 * the shell).
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function loadEnvFromFile(envPath: string): void {
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

export default async function globalSetup(): Promise<void> {
  // Walk up two levels — frontend/e2e → frontend → repo root.
  loadEnvFromFile(path.resolve(__dirname, '..', '..', '.env'))

  const apiKey =
    process.env.BROKER_API_KEY || process.env.ALPACA_API_KEY || ''
  const apiSecret =
    process.env.BROKER_API_SECRET || process.env.ALPACA_API_SECRET || ''

  if (!apiKey || !apiSecret) {
    // No Alpaca credentials configured — the paper-trading tests
    // would have skipped/failed at first network call anyway. No
    // cleanup work to do.
    return
  }

  const base = apiKey.startsWith('PK')
    ? 'https://paper-api.alpaca.markets'
    : 'https://api.alpaca.markets'

  const headers = {
    'APCA-API-KEY-ID': apiKey,
    'APCA-API-SECRET-KEY': apiSecret,
  }

  try {
    const list = await fetch(`${base}/v2/orders?status=open&limit=500`, {
      headers,
    })
    if (!list.ok) {
      // 401/403 means stale credentials; let tests surface the
      // real auth failure instead of swallowing it here.
      return
    }
    const orders = (await list.json()) as Array<{ id: string }>
    if (!Array.isArray(orders) || orders.length === 0) {
      return
    }
    const cancel = await fetch(`${base}/v2/orders`, {
      method: 'DELETE',
      headers,
    })
    if (cancel.status >= 200 && cancel.status < 300) {
      console.log(
        `[global-setup] Cancelled ${orders.length} leftover Alpaca open order(s)`,
      )
    }
  } catch {
    // Network blip — let tests proceed; they will surface any real
    // problem with their own assertions.
  }
}
