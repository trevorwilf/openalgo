import WebSocket from "ws";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KEY = fs.readFileSync(
  path.join(__dirname, "..", "tests", "e2e_smoke", "_artifacts", "api_key.txt"),
  "utf8",
).trim();
const ws = new WebSocket("ws://127.0.0.1:8765");
let nTicks = 0;
const start = Date.now();
ws.on("open", () => {
  ws.send(JSON.stringify({ action: "authenticate", api_key: KEY }));
});
ws.on("message", (raw) => {
  const m = raw.toString();
  let p; try { p = JSON.parse(m); } catch { return; }
  if (p.type === "auth" && p.status === "success") {
    console.log("[ws] auth ok");
    for (const sym of ["BTC-USD", "BTC/USD", "BTCUSD"]) {
      for (const exch of ["ALPACA_CRYPTO", "CRYPTO", "ALPACA"]) {
        ws.send(JSON.stringify({ action: "subscribe",
                                  symbols: [{ symbol: sym, exchange: exch }],
                                  mode: "Quote" }));
        console.log(`[ws] -> sub ${sym}@${exch}`);
      }
    }
  } else if (p.type === "subscribe") {
    console.log(`[ws] <- sub resp: ${(p.subscriptions||[])[0]?.symbol}@${(p.subscriptions||[])[0]?.exchange} ${(p.subscriptions||[])[0]?.status}`);
  } else if (p.type === "market_data" || p.symbol || p.ltp || p.last_price) {
    nTicks++;
    if (nTicks <= 3) console.log(`[ws] tick #${nTicks}: ${m.slice(0, 200)}`);
  } else if (p.type === "error") {
    console.log(`[ws] error: ${m.slice(0, 200)}`);
  }
});
setTimeout(() => {
  console.log(`[ws] ${nTicks} tick(s) in ${Date.now()-start}ms`);
  ws.close();
  process.exit(0);
}, 12000);
