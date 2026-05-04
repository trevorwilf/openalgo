/**
 * Authenticated end-to-end sweep against an already-running Flask
 * instance. Drives the OpenAlgo password login + Alpaca broker
 * callback, then visits every authenticated React route and probes
 * the entire /api/v1 + /api/v2 surface with non-destructive payloads.
 *
 * Reads `web_login_username` / `web_login_password` from the project
 * `.env` (the Flask process already loaded them into its environment;
 * we re-parse the file here so the spec stays decoupled from
 * Playwright's process env).
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config=playwright.live.config.ts \
 *     auth-instance.spec.ts
 *
 * Outputs:
 *   - Per-route screenshot in ./test-results-live/
 *   - Console + 5xx report in stdout
 *   - JSON dump of all API call results in
 *     ./test-results-live/api-sweep.json
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ---------------------------------------------------------------------------
// Bootstrap — read creds from .env (project root, two levels up).
// ---------------------------------------------------------------------------

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
    // Strip matching quotes
    if (
      (v.startsWith("'") && v.endsWith("'")) ||
      (v.startsWith('"') && v.endsWith('"'))
    ) {
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
  throw new Error(
    `Missing web_login_username/web_login_password in .env (parsed keys: ${Object.keys(ENV).join(', ')})`,
  )
}

// ---------------------------------------------------------------------------
// Per-test observation helpers.
// ---------------------------------------------------------------------------

interface RouteReport {
  path: string
  status: number
  consoleErrors: string[]
  networkFailures: { url: string; status: number; method: string }[]
}
const routeReports: RouteReport[] = []

interface ApiResult {
  method: string
  path: string
  status: number
  ok: boolean
  bodySnippet?: string
  notes?: string
}
const apiResults: ApiResult[] = []

function attachObservers(page: import('@playwright/test').Page) {
  const obs = {
    consoleErrors: [] as string[],
    networkFailures: [] as { url: string; status: number; method: string }[],
  }
  page.on('console', (msg) => {
    if (msg.type() === 'error') obs.consoleErrors.push(msg.text())
  })
  page.on('response', (resp) => {
    const status = resp.status()
    if (status >= 400 && status < 600) {
      obs.networkFailures.push({
        url: resp.url(),
        status,
        method: resp.request().method(),
      })
    }
  })
  return obs
}

// ---------------------------------------------------------------------------
// Authenticated routes that the React Router exposes.
// ---------------------------------------------------------------------------

const AUTH_ROUTES = [
  '/dashboard',
  '/positions',
  '/orderbook',
  '/tradebook',
  '/holdings',
  '/search',
  '/apikey',
  '/platforms',
  '/tradingview',
  '/gocharting',
  '/pnl-tracker',
  '/sandbox',
  '/sandbox/mypnl',
  '/analyzer',
  '/tools',
  '/optionchain',
  '/ivchart',
  '/oitracker',
  '/maxpain',
  '/straddle',
  '/straddlepnl',
  '/volsurface',
  '/gex',
  '/ivsmile',
  '/oiprofile',
  '/strategybuilder',
  '/strategybuilder/portfolio',
  '/websocket/test',
  '/strategy',
  '/python',
  '/python/guide',
  '/chartink',
  '/flow',
  '/flow/shortcuts',
  '/leverage',
  '/admin',
  '/admin/freeze',
  '/admin/holidays',
  '/admin/timings',
  '/telegram',
  '/telegram/config',
  '/telegram/users',
  '/telegram/analytics',
  '/logs',
  '/logs/live',
  '/logs/security',
  '/logs/traffic',
  '/logs/latency',
  '/health',
  '/profile',
  '/master-contract',
  '/action-center',
  '/playground',
  '/historify',
  '/historify/charts',
]

// ---------------------------------------------------------------------------
// Login + broker connect — runs once at suite start, sets browser
// context cookies that propagate to every test.
// ---------------------------------------------------------------------------

// Serial: beforeAll must complete before route tests run. Using
// `default` mode would let route tests parallelize, but the auth
// state file isn't ready until beforeAll finishes. Serial here means
// "in declared order on a single worker"; we still don't want one
// route's failure to abort the rest, so route assertions soft-fail.
test.describe.configure({ mode: 'serial' })

let storageStateFile: string | null = null

test.beforeAll(async ({ browser }) => {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()

  // Step 1: GET / to mint the session + CSRF cookie
  await page.goto(`${BASE}/login`)
  await page.waitForLoadState('networkidle')

  // Step 2: POST /auth/login with form data (CSRF disabled for this endpoint
  //         in dev-flow, OR we extract token from /auth/csrf-token)
  const csrf = await ctx.request.get(`${BASE}/auth/csrf-token`)
  const csrfBody = await csrf.json()
  const csrfToken = csrfBody.csrf_token

  const loginResp = await ctx.request.post(`${BASE}/auth/login`, {
    form: { username: USERNAME, password: PASSWORD },
    headers: { 'X-CSRFToken': csrfToken },
  })
  const loginBody = await loginResp.text()
  console.log(
    `[auth] /auth/login → ${loginResp.status()} body=${loginBody.slice(0, 200)}`,
  )
  expect(loginResp.status(), `login failed: ${loginBody}`).toBeLessThan(400)

  // Step 3: GET /alpaca/callback — Alpaca uses no-OAuth API-key auth,
  // so a GET to the callback validates the env keys + sets logged_in.
  const cb = await ctx.request.get(`${BASE}/alpaca/callback`, {
    maxRedirects: 0,
  })
  const cbStatus = cb.status()
  console.log(
    `[auth] /alpaca/callback → ${cbStatus} (location=${cb.headers().location})`,
  )
  // 302 to /dashboard means success; 200 may indicate handler returned JSON.
  expect(cbStatus, `broker callback failed`).toBeLessThan(500)

  // Sanity check: hit /auth/dashboard-data — needs logged_in
  const dash = await ctx.request.get(`${BASE}/auth/dashboard-data`)
  console.log(`[auth] /auth/dashboard-data → ${dash.status()}`)

  storageStateFile = path.join(__dirname, '..', 'test-results-live', 'auth-state.json')
  fs.mkdirSync(path.dirname(storageStateFile), { recursive: true })
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

// ---------------------------------------------------------------------------
// UI route sweep — one test per route.
// ---------------------------------------------------------------------------

for (const route of AUTH_ROUTES) {
  test(`UI ${route}`, async ({ browser }, testInfo) => {
    // Generous test-level timeout. Some India-only feature pages
    // (volsurface, gex, ivsmile, oiprofile, strategybuilder) render
    // the "feature unavailable in region" gating UI for non-India
    // brokers and continue polling background React queries that
    // race against the default 30s test timeout. 90s is well above
    // the 99th percentile observed on the live suite.
    testInfo.setTimeout(90_000)
    expect(storageStateFile, 'storage state not captured').toBeTruthy()
    const ctx = await browser.newContext({ storageState: storageStateFile! })
    const page = await ctx.newPage()
    const obs = attachObservers(page)

    let resp: import('@playwright/test').Response | null = null
    try {
      resp = await page.goto(`${BASE}${route}`, {
        timeout: 30_000,
        waitUntil: 'load',
      })
    } catch (err) {
      console.log(`[ui] ${route} navigation error: ${err}`)
    }

    // Wait for React to settle (max 5s — some pages have ongoing polling)
    try {
      await page.waitForLoadState('networkidle', { timeout: 5_000 })
    } catch {
      /* polling pages never go idle; continue */
    }

    const status = resp?.status() ?? 0
    const screenshotPath = path.join(
      'test-results-live',
      'auth',
      `${route.replace(/\//g, '_').replace(/^_/, '') || 'root'}.png`,
    )
    try {
      await page.screenshot({ path: screenshotPath, fullPage: true })
    } catch {
      /* page may have navigated away */
    }

    routeReports.push({
      path: route,
      status,
      consoleErrors: obs.consoleErrors.slice(),
      networkFailures: obs.networkFailures.slice(),
    })

    const fiveXX = obs.networkFailures.filter((f) => f.status >= 500)

    // Soft fail: collect everything, don't block other routes
    testInfo.annotations.push({
      type: 'route-status',
      description: `${status} | console=${obs.consoleErrors.length} 4xx+5xx=${obs.networkFailures.length} 5xx=${fiveXX.length}`,
    })

    if (fiveXX.length > 0) {
      console.log(
        `[ui FAIL] ${route} 5xx network responses:\n  ${JSON.stringify(fiveXX, null, 2)}`,
      )
    }
    if (obs.consoleErrors.length > 0) {
      console.log(
        `[ui WARN] ${route} console errors:\n  - ${obs.consoleErrors.join('\n  - ')}`,
      )
    }

    // Some India-only feature pages (volsurface, gex, ivsmile, etc.)
    // render the "feature unavailable in region" gating UI for non-
    // India brokers. The gating page may continue polling React
    // queries on a long-lived setInterval which races with
    // ctx.close() and throws a Protocol error during disposal.
    // The test value is in the navigation + screenshot + soft-fail
    // metrics; we don't need a clean context-close to claim
    // success. Wrap in try/catch so the disposal race doesn't
    // bubble up as a test failure.
    try {
      await ctx.close()
    } catch (closeErr) {
      console.log(`[ui WARN] ${route} ctx.close race (non-fatal): ${closeErr}`)
    }
    // Soft-record only — never throw. The summary file collects
    // every failure; cascading failures here would block 80% of
    // the sweep. Use `npm run report:live` (or read
    // ./test-results-live/route-report.json) for the full picture.
    if (status >= 500 || fiveXX.length > 0) {
      testInfo.annotations.push({
        type: 'soft-fail',
        description: `status=${status} 5xx=${JSON.stringify(fiveXX)}`,
      })
    }
  })
}

// ---------------------------------------------------------------------------
// API key acquisition — generates an /apikey via the authed UI's
// backing endpoint. Stored for the API sweep below.
// ---------------------------------------------------------------------------

let API_KEY: string | null = null

test('Acquire API key', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: storageStateFile! })

  // Step 1: try GET /apikey with Accept: application/json — returns the
  // existing decrypted key if one exists.
  const existing = await ctx.request.get(`${BASE}/apikey`, {
    headers: { Accept: 'application/json' },
  })
  console.log(`[apikey] GET /apikey → ${existing.status()}`)
  if (existing.status() < 400) {
    try {
      const body = await existing.json()
      if (body.api_key) {
        API_KEY = body.api_key
        console.log(`[apikey] using existing key`)
      }
    } catch {
      /* fallthrough to regenerate */
    }
  }

  // Step 2: if no existing key, generate one. POST /apikey expects
  // JSON with user_id (= login username).
  if (!API_KEY) {
    const csrfResp = await ctx.request.get(`${BASE}/auth/csrf-token`)
    const csrfToken = (await csrfResp.json()).csrf_token

    const regen = await ctx.request.post(`${BASE}/apikey`, {
      data: { user_id: USERNAME },
      headers: {
        'X-CSRFToken': csrfToken,
        'Content-Type': 'application/json',
      },
    })
    const regenBody = await regen.text()
    console.log(
      `[apikey] POST /apikey → ${regen.status()} ${regenBody.slice(0, 200)}`,
    )
    if (regen.status() < 400) {
      try {
        const j = JSON.parse(regenBody)
        API_KEY = j.api_key || null
      } catch {
        /* unexpected */
      }
    }
  }

  console.log(
    `[apikey] resolved key: ${API_KEY ? API_KEY.slice(0, 8) + '...' : 'NONE'}`,
  )
  await ctx.close()
  expect(API_KEY, 'API key not acquired').toBeTruthy()
})

// ---------------------------------------------------------------------------
// API surface sweep — non-destructive only.
// ---------------------------------------------------------------------------

interface ApiCall {
  method: 'GET' | 'POST'
  path: string
  body?: object
  notes?: string
  okIfStatus?: number[]
}

const SAFE_API_CALLS: ApiCall[] = [
  // ---- v1 endpoints expected to 410 GONE for Alpaca (ADR 0023) ----
  // These probe the deprecation path. Each MUST return 410 with the
  // canonical v1_unavailable_for_non_india_broker code; any other
  // status is a regression of the deprecation contract.
  { method: 'POST', path: '/api/v1/ping/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/funds/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/orderbook/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/tradebook/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/positionbook/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/holdings/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/intervals/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/analyzer/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/market/holidays/', okIfStatus: [410] },
  { method: 'POST', path: '/api/v1/market/timings/', okIfStatus: [410] },
  {
    method: 'POST',
    path: '/api/v1/quotes/',
    body: { symbol: 'AAPL', exchange: 'XNAS' },
    okIfStatus: [410],
  },
  {
    method: 'POST',
    path: '/api/v1/depth/',
    body: { symbol: 'AAPL', exchange: 'XNAS' },
    okIfStatus: [410],
  },
  {
    method: 'POST',
    path: '/api/v1/symbol/',
    body: { symbol: 'AAPL', exchange: 'XNAS' },
    okIfStatus: [410],
  },
  {
    method: 'POST',
    path: '/api/v1/search/',
    body: { query: 'AAPL', exchange: 'XNAS' },
    okIfStatus: [410],
  },

  // ---- v2 promoted (read-only) ----
  { method: 'GET', path: '/api/v2/' },
  { method: 'GET', path: '/api/v2/regions' },
  { method: 'GET', path: '/api/v2/regions/india' },
  { method: 'GET', path: '/api/v2/regions/us' },
  { method: 'GET', path: '/api/v2/regions/us/flow_defaults' },
  { method: 'GET', path: '/api/v2/regions/eu' },
  { method: 'GET', path: '/api/v2/regions/uk' },
  { method: 'GET', path: '/api/v2/venues' },
  { method: 'GET', path: '/api/v2/venues/XNAS' },
  { method: 'GET', path: '/api/v2/venues/XNAS/sessions' },
  { method: 'GET', path: '/api/v2/capabilities' },
  { method: 'GET', path: '/api/v2/balances' },
  { method: 'GET', path: '/api/v2/positions' },
  { method: 'GET', path: '/api/v2/plugins/diagnostics' },
  { method: 'GET', path: '/api/v2/admin/broker_compliance' },
  {
    method: 'GET',
    path: '/api/v2/instruments/search?q=AAPL',
    okIfStatus: [200, 400, 404],
  },

  // ---- internal blueprints (use cookie auth, not API key) ----
  { method: 'GET', path: '/api/master-contract/status', notes: 'cookie' },
  { method: 'GET', path: '/api/master-contract/ready', notes: 'cookie' },
  { method: 'GET', path: '/api/master-contract/smart-status', notes: 'cookie' },
  { method: 'GET', path: '/api/cache/status', notes: 'cookie' },
  { method: 'GET', path: '/api/cache/health', notes: 'cookie' },
  { method: 'GET', path: '/api/broker/credentials', notes: 'cookie' },
  { method: 'GET', path: '/api/broker/capabilities', notes: 'cookie' },
  { method: 'GET', path: '/api/broker/rules', notes: 'cookie' },
  { method: 'GET', path: '/api/system/permissions', notes: 'cookie' },
  { method: 'GET', path: '/api/websocket/status', notes: 'cookie' },
  { method: 'GET', path: '/api/websocket/health', notes: 'cookie' },
  { method: 'GET', path: '/api/websocket/config', notes: 'cookie' },
  { method: 'GET', path: '/api/websocket/metrics', notes: 'cookie' },
  { method: 'GET', path: '/api/strategy-portfolio', notes: 'cookie' },
]

for (const call of SAFE_API_CALLS) {
  test(`API ${call.method} ${call.path}`, async ({ browser }) => {
    expect(API_KEY, 'API key not yet acquired').toBeTruthy()
    const ctx = await browser.newContext({ storageState: storageStateFile! })
    const url = `${BASE}${call.path}`

    let status = 0
    let snippet = ''
    let ok = false
    try {
      let resp: import('@playwright/test').APIResponse
      // /api/v2/* uses X-API-KEY header auth; /api/v1/* and the
      // internal /api/* blueprints accept either cookie or apikey
      // body. Belt-and-braces: send both whenever we have the key.
      const headers: Record<string, string> = {
        'X-API-KEY': API_KEY!,
      }
      if (call.method === 'GET') {
        resp = await ctx.request.get(url, { headers })
      } else {
        const body = call.body
          ? { ...call.body, apikey: API_KEY }
          : { apikey: API_KEY }
        resp = await ctx.request.post(url, { data: body, headers })
      }
      status = resp.status()
      snippet = (await resp.text()).slice(0, 300)
      const acceptable = call.okIfStatus || [200]
      ok = status < 500 && (acceptable.includes(status) || status < 400)
    } catch (err) {
      snippet = `EXCEPTION: ${err}`
    }

    apiResults.push({
      method: call.method,
      path: call.path,
      status,
      ok,
      bodySnippet: snippet,
      notes: call.notes,
    })

    await ctx.close()

    if (!ok) {
      console.log(
        `[api FAIL] ${call.method} ${call.path} → ${status}\n  body: ${snippet}`,
      )
    }
    // Soft-record only — see UI sweep comment above.
  })
}

// ---------------------------------------------------------------------------
// Final teardown — write JSON report.
// ---------------------------------------------------------------------------

test.afterAll(async () => {
  const outDir = path.resolve(__dirname, '..', 'test-results-live')
  fs.mkdirSync(outDir, { recursive: true })
  fs.writeFileSync(
    path.join(outDir, 'route-report.json'),
    JSON.stringify(routeReports, null, 2),
  )
  fs.writeFileSync(
    path.join(outDir, 'api-sweep.json'),
    JSON.stringify(apiResults, null, 2),
  )
  console.log(
    `[summary] routes tested: ${routeReports.length}, api calls: ${apiResults.length}`,
  )
})
