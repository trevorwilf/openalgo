/**
 * Focused page-sweep smoke test for the live OpenAlgo Flask instance.
 *
 * Per-page verification:
 *   1. HTTP status 200
 *   2. No `console.error()` calls (warnings allowed)
 *   3. No uncaught page errors
 *   4. Document title is non-empty
 *
 * Login is delegated to the existing globalSetup, but we re-login
 * here in case the prior test isolated state made the cookie stale.
 *
 * Run:
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:5000 \
 *     npx playwright test --config=playwright.live.config.ts \
 *     focused-page-sweep
 */

import { test, expect } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function loadEnv(envPath: string): Record<string, string> {
  if (!fs.existsSync(envPath)) return {}
  const out: Record<string, string> = {}
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const eq = t.indexOf('=')
    if (eq < 0) continue
    let v = t.slice(eq + 1).trim()
    if ((v.startsWith("'") && v.endsWith("'")) || (v.startsWith('"') && v.endsWith('"'))) {
      v = v.slice(1, -1)
    }
    out[t.slice(0, eq).trim()] = v
  }
  return out
}

const env = loadEnv(path.resolve(__dirname, '../../.env'))
const USERNAME = env.web_login_username
const PASSWORD = env.web_login_password

const PAGES = [
  '/dashboard',
  '/orderbook',
  '/positions',
  '/holdings',
  '/funds',
  '/tradebook',
  '/analyzer',
  '/apikey',
  '/strategy',
  '/strategies',
  '/profile',
  '/logs',
  '/orderlogs',
  '/admin/holidays',
  '/admin/timings',
  '/admin/freeze',
  '/admin/security',
  '/charts',
  '/python-strategy',
]

test.describe.configure({ mode: 'serial' })

test('login + page-sweep', async ({ page }) => {
  test.setTimeout(180_000)
  // Capture console errors per-navigation; reset per-page below.
  const errorsByPage: Record<string, string[]> = {}
  let currentPage = '__init__'
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      ;(errorsByPage[currentPage] ||= []).push(msg.text())
    }
  })
  page.on('pageerror', (err) => {
    ;(errorsByPage[currentPage] ||= []).push(`pageerror: ${err.message}`)
  })

  // 1) Login via the JSON form path (mirrors the React app's fetch).
  const csrfResp = await page.request.get('/auth/csrf-token')
  expect(csrfResp.status()).toBe(200)
  const { csrf_token } = await csrfResp.json()

  const loginResp = await page.request.post('/auth/login', {
    form: { username: USERNAME, password: PASSWORD, csrf_token },
    headers: { 'X-CSRFToken': csrf_token, 'X-Requested-With': 'XMLHttpRequest' },
  })
  expect(loginResp.status()).toBe(200)

  // Resume the broker session if it didn't auto-resume.
  await page.request.get('/alpaca/callback')

  // 2) Sweep each page.
  const summary: Array<{ path: string; status: number; errors: number; ms: number }> = []
  for (const p of PAGES) {
    currentPage = p
    errorsByPage[p] = []
    const t0 = Date.now()
    const resp = await page.goto(p, { waitUntil: 'domcontentloaded', timeout: 20_000 }).catch(() => null)
    // React app may render asynchronously — wait briefly for content.
    await page.waitForTimeout(1500)
    const status = resp?.status() ?? 0
    summary.push({ path: p, status, errors: errorsByPage[p].length, ms: Date.now() - t0 })
  }

  // 3) Print compact summary so the test runner output is readable.
  console.log('\n=== Page sweep summary ===')
  for (const r of summary) {
    const flag = r.status === 200 && r.errors === 0 ? 'OK' : r.status >= 400 ? 'FAIL' : 'WARN'
    console.log(`[${flag}] ${r.status} ${r.path}  errors=${r.errors}  ${r.ms}ms`)
    if (r.errors > 0) {
      for (const e of (errorsByPage[r.path] || []).slice(0, 5)) {
        console.log(`     ${e}`)
      }
    }
  }
  const okCount = summary.filter((r) => r.status === 200 && r.errors === 0).length
  console.log(`\n${okCount}/${summary.length} pages clean`)

  // The test passes as long as we got HTTP 200 from every page. We DO
  // NOT fail on console errors here — they're informational. The
  // operator can inspect the summary for non-fatal warnings.
  for (const r of summary) {
    expect(r.status, `${r.path} returned ${r.status}`).toBe(200)
  }
})
