// Deeper interactive UI sweep:
// - login
// - dashboard tile rendering (check Collateral / Funds shows USD not INR)
// - /search: type a query and verify results render
// - /orderbook: confirm table renders without error
// - /apikey: verify form renders with the existing key
// - /settings: verify settings page renders with form fields

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { config as loadEnv } from "dotenv";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
function findEnv(start) {
  let dir = start;
  for (let i = 0; i < 6; i++) {
    const p = path.join(dir, ".env");
    if (fs.existsSync(p)) return p;
    const parent = path.dirname(dir); if (parent === dir) break; dir = parent;
  }
  return null;
}
const ENV = findEnv(__dirname); if (ENV) loadEnv({ path: ENV });

const BASE = process.env.HOST_SERVER?.replace(/\/$/, "") || "http://127.0.0.1:5000";
const USER = process.env.web_login_username;
const PASS = process.env.web_login_password;
const REPO = ENV ? path.dirname(ENV) : path.resolve(__dirname, "..");
const ART = path.join(REPO, "tests", "e2e_smoke", "_artifacts", "deep_ui");
fs.mkdirSync(ART, { recursive: true });

const consoleErrors = [];
const pageErrors = [];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ baseURL: BASE });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() }); });
  page.on("pageerror", (e) => pageErrors.push({ url: page.url(), text: e.message }));

  console.log("[1/7] login");
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[type='password']", { timeout: 20000 });
  await page.fill("input[type='text']:not([type='hidden'])", USER);
  await page.fill("input[type='password']", PASS);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auth/login") && r.request().method() === "POST", { timeout: 25000 }).catch(() => null),
    page.click("button[type='submit'], button:has-text('Login'), button:has-text('Sign in')"),
  ]);
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  for (let i = 0; i < 10 && /\/login/.test(page.url()); i++) await page.waitForTimeout(500);
  console.log(`     -> ${page.url()}`);

  console.log("[2/7] dashboard tile content");
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  const dashText = await page.evaluate(() => document.body.innerText.slice(0, 4000));
  await page.screenshot({ path: path.join(ART, "dashboard.png"), fullPage: true });
  fs.writeFileSync(path.join(ART, "dashboard_text.txt"), dashText);
  // Quick checks: should have USD or $ symbols (alpaca region us). Should NOT be all INR / ₹.
  const usdHit = /USD|\$/i.test(dashText);
  const inrHit = /₹|INR/i.test(dashText);
  console.log(`     usd=${usdHit} inr=${inrHit} text_len=${dashText.length}`);

  console.log("[3/7] /search interaction");
  await page.goto("/search", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
  // Try to find a search input — common patterns.
  const searchInput = await page.$("input[type='search'], input[placeholder*='symbol' i], input[placeholder*='search' i], input[role='searchbox']");
  if (searchInput) {
    await searchInput.fill("AAPL");
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(ART, "search_aapl.png"), fullPage: true });
    const text = await page.evaluate(() => document.body.innerText);
    const hit = /AAPL/.test(text);
    console.log(`     AAPL appears in body: ${hit}`);
  } else {
    console.log("     no search input found; capturing screenshot");
    await page.screenshot({ path: path.join(ART, "search_no_input.png"), fullPage: true });
  }

  console.log("[4/7] /orderbook table");
  await page.goto("/orderbook", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page.screenshot({ path: path.join(ART, "orderbook.png"), fullPage: true });
  const obText = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  fs.writeFileSync(path.join(ART, "orderbook_text.txt"), obText);
  // The previous live test showed one historical order; check if it surfaces.
  console.log(`     text_len=${obText.length}`);

  console.log("[5/7] /apikey shows existing key");
  await page.goto("/apikey", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
  await page.screenshot({ path: path.join(ART, "apikey.png"), fullPage: true });
  const akText = await page.evaluate(() => document.body.innerText);
  // Should show the (decrypted) existing key or a button to view/regenerate
  console.log(`     contains 'API Key' header: ${/API Key/i.test(akText)}`);

  console.log("[6/7] /settings render");
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
  await page.screenshot({ path: path.join(ART, "settings.png"), fullPage: true });
  const setText = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  fs.writeFileSync(path.join(ART, "settings_text.txt"), setText);
  console.log(`     text_len=${setText.length}`);

  console.log("[7/7] /master_contract status");
  await page.goto("/master_contract", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
  await page.screenshot({ path: path.join(ART, "master_contract.png"), fullPage: true });

  fs.writeFileSync(path.join(ART, "errors.json"), JSON.stringify({
    consoleErrors, pageErrors,
  }, null, 2));
  console.log(`[done] console_errors=${consoleErrors.length} page_errors=${pageErrors.length}`);
  if (consoleErrors.length || pageErrors.length) {
    console.log("--- errors ---");
    [...consoleErrors, ...pageErrors].slice(0, 20).forEach((e) => {
      console.log(`  [${e.url}] ${e.text.slice(0, 240)}`);
    });
  }
  await browser.close();
}

main().catch((e) => { console.error("FATAL", e); process.exit(1); });
