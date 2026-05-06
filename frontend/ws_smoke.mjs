// Quick WebSocket smoke: auth + subscribe to AAPL on alpaca.
import WebSocket from "ws";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KEY = fs.readFileSync(
  path.join(__dirname, "..", "tests", "e2e_smoke", "_artifacts", "api_key.txt"),
  "utf8",
).trim();

const URL = "ws://127.0.0.1:8765";
console.log(`[ws] connecting ${URL}`);
const ws = new WebSocket(URL);
const events = [];
const start = Date.now();

ws.on("open", () => {
  console.log("[ws] open");
  ws.send(JSON.stringify({ action: "authenticate", api_key: KEY }));
});

ws.on("message", (raw) => {
  const msg = raw.toString();
  console.log(`[ws] <- ${msg.slice(0, 250)}`);
  events.push(msg);
  let parsed;
  try { parsed = JSON.parse(msg); } catch { return; }
  if (parsed.action === "authenticate" || parsed.type === "authenticate" ||
      (parsed.status === "success" && /authent/i.test(parsed.message || ""))) {
    setTimeout(() => {
      // Try common exchange codes Alpaca's WS adapter might accept.
      for (const exch of ["NSE", "XNAS", "NASDAQ"]) {
        const sub = { action: "subscribe",
                       symbols: [{ symbol: "AAPL", exchange: exch }],
                       mode: "Quote" };
        console.log(`[ws] -> subscribe AAPL@${exch}`);
        ws.send(JSON.stringify(sub));
      }
    }, 200);
  }
});

ws.on("error", (e) => console.error(`[ws] error ${e.message}`));
ws.on("close", () => console.log(`[ws] close after ${Date.now()-start}ms (${events.length} events)`));

setTimeout(() => {
  console.log("[ws] closing after 8s");
  ws.close();
  process.exit(0);
}, 8000);
