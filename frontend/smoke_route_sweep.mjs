// Sweep every actual user-facing React route + detect SPA-level 404s.
//
// Flask serves the SPA shell at any unknown URL → HTTP 200 even for
// routes that don't exist in React. The ONLY way to verify the route
// truly exists is to load it and check whether the React tree renders
// the NotFound page ("404 - Page Not Found").

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { config as loadEnv } from "dotenv";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
function findEnv(s) { let d = s; for (let i=0;i<6;i++){const p=path.join(d,'.env');if(fs.existsSync(p))return p;const pa=path.dirname(d);if(pa===d)break;d=pa;} return null; }
loadEnv({ path: findEnv(__dirname) });
const BASE = "http://127.0.0.1:5000";
const USER = process.env.web_login_username;
const PASS = process.env.web_login_password;
const REPO = path.dirname(findEnv(__dirname));
const ART = path.join(REPO, "tests", "e2e_smoke", "_artifacts", "routes");
fs.mkdirSync(ART, { recursive: true });

// Routes derived from frontend/src/config/navigation.ts + App.tsx scan
const ROUTES = [
  // navItems
  "/dashboard", "/orderbook", "/tradebook", "/positions", "/action-center",
  "/platforms", "/strategy", "/logs", "/tools",
  // profileMenuItems
  "/profile", "/apikey", "/master-contract", "/telegram", "/holdings",
  "/flow", "/python", "/pnl-tracker", "/charts", "/search/token", "/sandbox",
  // additional routes from App.tsx
  "/funds", "/health", "/logs/traffic", "/logs/latency", "/playground",
  "/leverage",
];

const results = [];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ baseURL: BASE });
  const page = await ctx.newPage();

  // Login
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[type='password']", { timeout: 20000 });
  await page.fill("input[type='text']:not([type='hidden'])", USER);
  await page.fill("input[type='password']", PASS);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auth/login") && r.request().method() === "POST", { timeout: 25000 }).catch(() => null),
    page.click("button[type='submit']"),
  ]);
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  for (let i = 0; i < 10 && /\/login/.test(page.url()); i++) await page.waitForTimeout(500);

  for (const route of ROUTES) {
    const consoleErrors = [];
    const onConsole = (m) => { if (m.type() === "error") consoleErrors.push(m.text()); };
    page.on("console", onConsole);
    try {
      await page.goto(route, { waitUntil: "domcontentloaded", timeout: 25000 });
      await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(500);
      const text = await page.evaluate(() => document.body.innerText.slice(0, 500));
      const is404 = /404\s*-?\s*Page Not Found|page (you'?re looking for )?(doesn'?t exist)|Page Not Found/i.test(text);
      const isIndiaOnly = /not available in your region|India region only|India-only/i.test(text);
      const isLogin = /\/login$/.test(page.url());
      results.push({
        route, final_url: page.url().replace(BASE, ""),
        is_404: is404, is_india_only: isIndiaOnly, redirected_to_login: isLogin,
        text_preview: text.slice(0, 150).replace(/\n/g, " "),
        console_error_count: consoleErrors.length,
      });
      console.log(`  ${route.padEnd(28)} ${is404 ? "404" : isIndiaOnly ? "IN-only" : isLogin ? "→login" : "ok"}`);
    } catch (e) {
      results.push({ route, error: e.message });
      console.log(`  ${route.padEnd(28)} EXC ${e.message.slice(0, 60)}`);
    } finally {
      page.off("console", onConsole);
    }
  }

  fs.writeFileSync(path.join(ART, "results.json"), JSON.stringify({ results }, null, 2));
  const real404s = results.filter((r) => r.is_404);
  const oks = results.filter((r) => !r.is_404 && !r.is_india_only && !r.redirected_to_login && !r.error);
  const indiaOnly = results.filter((r) => r.is_india_only);
  console.log(`\n[summary] ok=${oks.length}/${results.length} 404=${real404s.length} india_only=${indiaOnly.length}`);
  if (real404s.length) {
    console.log("--- React 404s ---");
    real404s.forEach((r) => console.log(`  ${r.route} (final_url=${r.final_url})`));
  }
  if (indiaOnly.length) {
    console.log("--- India-only ---");
    indiaOnly.forEach((r) => console.log(`  ${r.route}`));
  }
  await browser.close();
}

main().catch((e) => { console.error("FATAL", e); process.exit(1); });
