/**
 * Verify India-only pages render the structured "feature unavailable"
 * empty state for non-India brokers, instead of the previous broken
 * shell that 404s sub-routes and shows blank widgets.
 *
 * Each India-only route should:
 *  - Return HTTP 200 from Flask (the React route still mounts).
 *  - Render the ``data-testid="india-only-feature-blocked"`` element.
 *  - NOT issue any of the broken sub-route requests (e.g.
 *    ``/api/v1/expiry``, ``/pnltracker/api/pnl``,
 *    ``/X/api/intervals``) — those would 404 and clutter the
 *    operator's network log.
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
    'paper-trading-india-gating',
    'auth-state.json',
  )
  fs.mkdirSync(path.dirname(storageStateFile), { recursive: true })
  await ctx.storageState({ path: storageStateFile })
  await ctx.close()
})

const INDIA_ONLY_ROUTES = [
  '/pnl-tracker',
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
  '/historify',
  '/chartink',
]

for (const route of INDIA_ONLY_ROUTES) {
  test(`${route} renders the india-only empty state for Alpaca`, async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: storageStateFile })
    const page = await ctx.newPage()
    const failures: { url: string; status: number }[] = []
    page.on('response', (r) => {
      const status = r.status()
      if (status >= 400 && status < 600) {
        failures.push({ url: r.url(), status })
      }
    })

    const resp = await page.goto(`${BASE}${route}`)
    expect(resp?.status()).toBeLessThan(400)
    await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => {})

    // Empty-state element MUST be present.
    await expect(
      page.getByTestId('india-only-feature-blocked'),
      `${route} did not render the india-only empty state`,
    ).toBeVisible({ timeout: 5_000 })

    // No broken India-specific subroute requests should fire.
    const brokenSubroutes = failures.filter((f) =>
      /\/(api\/v1\/expiry|pnltracker\/api|api\/intervals|api\/historify-intervals)/.test(
        f.url,
      ),
    )
    expect(
      brokenSubroutes,
      `${route} fired broken India sub-routes: ${JSON.stringify(brokenSubroutes)}`,
    ).toEqual([])

    await ctx.close()
  })
}
