# Alpaca Markets — OpenAlgo broker plugin

Alpaca Markets is OpenAlgo's first non-India broker plugin. It runs
exclusively on the **promoted lane** (`/api/v2`) per
[ADR 0005](../../docs/adr/0005-two-lanes-legacy-and-promoted.md):
the legacy India `/api/v1` lane refuses non-India brokers at the
request guard.

## At a glance

| Field | Value |
|-------|-------|
| Region | `us` |
| Market families | `US_STOCK`, `CRYPTO` |
| Asset classes | `EQUITY`, `ETF`, `SPOT` (crypto) |
| Auth style | API key + secret in HTTP headers (no OAuth) |
| Settlement | T+1 (equities; effective May 28, 2024) |
| Sessions | Regular (09:30–16:00 ET) + extended hours (04:00–20:00 ET) + 24/7 crypto |
| Quantity units | Whole, fractional, notional |
| Order types | MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP, MARKET_ON_OPEN, LIMIT_ON_OPEN, MARKET_ON_CLOSE, LIMIT_ON_CLOSE |
| Time-in-force | DAY, GTC, IOC, FOK, OPG, ATC |
| Bracket orders | OCO, OTO, OTOCO (Alpaca's `bracket`) |
| Fractional shares | ✅ |
| Notional orders | ✅ |
| Short selling | ✅ (subject to Alpaca's `shortable` flag per asset) |
| Crypto | ✅ (BTC/USD, ETH/USD, etc., 24/7) |

The plugin manifest pins these capabilities; the loader rejects any
attempt to use a feature that isn't declared.

## Setup

The plugin reads credentials in two precedence-ordered ways. Pick one.

### Option 1 — Alpaca-prefixed env vars (recommended for shared boxes)

```dotenv
ALPACA_API_KEY    = '<your APCA-API-KEY-ID>'
ALPACA_API_SECRET = '<your APCA-API-SECRET-KEY>'
ALPACA_PAPER      = '1'   # default; set to '0' for live
```

This style works alongside other brokers in `VALID_BROKERS` because
the variable names are Alpaca-specific.

### Option 2 — Generic `BROKER_API_*` (single-broker deployments)

```dotenv
# Paper-trading credentials (default mode)
BROKER_API_KEY        = '<your paper APCA-API-KEY-ID>'
BROKER_API_SECRET     = '<your paper APCA-API-SECRET-KEY>'

# Live-trading credentials (used when ALPACA_LIVE_MODE=1)
BROKER_API_KEY_MARKET    = '<your live APCA-API-KEY-ID>'
BROKER_API_SECRET_MARKET = '<your live APCA-API-SECRET-KEY>'

ALPACA_LIVE_MODE = '0'    # default; set to '1' to use the _MARKET pair
```

This style fits OpenAlgo's single-broker-per-instance model: the
operator drops Alpaca keys into the standard slots and toggles
between paper and live with a single flag flip.

### Both styles

* Add `alpaca` to `VALID_BROKERS`:
  ```
  VALID_BROKERS = '...,alpaca'
  ```
* `REDIRECT_URL` is required by the framework but unused by Alpaca's
  API-key flow:
  ```
  REDIRECT_URL = 'http://127.0.0.1:5000/alpaca/callback'
  ```

If both Option 1 and Option 2 are populated, **Option 1 wins**.
Placeholder values from `.sample.env` (`YOUR_BROKER_API_KEY`, etc.)
are treated as missing — you'll get a clear error at startup rather
than an obscure 401 from Alpaca.

### Optional streaming-feed selector

```dotenv
# 'iex' (default; free), 'sip' (paid SIP feed), or 'crypto'
ALPACA_STREAM_FEED = 'iex'

# Full-URL override — wins over ALPACA_STREAM_FEED.
# ALPACA_STREAM_BASE = 'wss://stream.data.alpaca.markets/v2/iex'
```

A single adapter instance subscribes to a single feed; for mixed
equity + crypto, run two adapters (one per session/process).

## Endpoints

| Mode | REST base | Streaming base (equity) | Streaming base (crypto) |
|------|-----------|-------------------------|-------------------------|
| Paper | `https://paper-api.alpaca.markets` | `wss://stream.data.alpaca.markets/v2/iex` | `wss://stream.data.alpaca.markets/v1beta3/crypto/us` |
| Live | `https://api.alpaca.markets` | `wss://stream.data.alpaca.markets/v2/iex` | `wss://stream.data.alpaca.markets/v1beta3/crypto/us` |

The paper/live split is for **trading**; market-data feeds are the
same regardless of mode.

## Connectivity smoke test

Before placing any orders, validate your credentials + reachability:

```bash
uv run python scripts/smoke/alpaca_paper_smoke.py
```

The script calls `GET /v2/account` (read-only — never places an
order) and prints the canonical account fields. A healthy paper
account looks like this:

```text
Mode:       PAPER
Base URL:   https://paper-api.alpaca.markets
Key prefix: PKH45M...

/v2/account response (selected fields):
{
  "id": "...",
  "account_number": "PA...",
  "status": "ACTIVE",
  "currency": "USD",
  "cash": "100000",
  "buying_power": "200000",
  ...
  "trading_blocked": false,
  "transfers_blocked": false,
  "account_blocked": false
}

[OK] account is active and not blocked.
```

If the smoke fails:

| Failure | Likely cause |
|---------|--------------|
| `credential resolution: ... missing` | Neither Option 1 nor Option 2 env vars set; or values match a `.sample.env` placeholder |
| `[FAIL] 401 Unauthorized` | Wrong key / secret, or live key used in paper mode (or vice versa) |
| `[FAIL] 403 Forbidden` | Key lacks the requested permission (e.g. live-trading on a paper-only key) |
| Network / timeout | Firewall, VPN, or Alpaca platform issue |

## Module layout

```
broker/alpaca/
├── plugin.json              capability manifest (loads via plugin_loader)
├── README.md                this file
├── PROMOTED                 sentinel — non-India, v2-only
├── api/
│   ├── auth_api.py          AlpacaAuth + dual-source credential resolution
│   ├── order_api.py         AlpacaOrderTranslator (BrokerOrderTranslator) +
│   │                        validate_combo / to_native_combo for OCO/OTO/OTOCO
│   ├── quote_api.py         AlpacaQuoteAdapter (latest quotes)
│   ├── bar_api.py           AlpacaBarAdapter (historical bars)
│   └── account_api.py       get_account_snapshot() (normalized funds shape)
├── streaming/
│   ├── alpaca_websocket.py  protocol client w/ reconnect + auto-resubscribe
│   └── alpaca_adapter.py    BaseBrokerWebSocketAdapter — IEX / SIP / crypto feeds
├── sync/
│   ├── instrument_sync.py   /v2/assets → instruments_repo (equity + crypto)
│   └── seed_rules.py        seeds Alpaca-specific BrokerRules entries
├── database/
│   └── master_contract_db.py  master_contract_download() entrypoint
└── mapping/
    └── transform_data.py    canonical Alpaca ↔ OpenAlgo vocabulary tables
                             (venue / order type / TIF / combo / symbol /
                             extended-hours sessions / crypto venues)
```

## Capabilities (per `plugin.json`)

```json
{
  "supported_regions":     ["us"],
  "market_families":       ["US_STOCK", "CRYPTO"],
  "supported_venue_codes": ["XNAS", "XNYS", "ARCX", "BATS", "CRYPTO"],
  "supported_asset_classes":["EQUITY", "ETF", "SPOT"],
  "supported_order_types": [
      "MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAILING_STOP",
      "MARKET_ON_OPEN", "LIMIT_ON_OPEN",
      "MARKET_ON_CLOSE", "LIMIT_ON_CLOSE"
  ],
  "supported_time_in_force":["DAY", "GTC", "IOC", "FOK", "OPG", "ATC"],
  "supported_sessions":     ["REGULAR", "PRE_MARKET", "POST_MARKET", "EXTENDED"],
  "supports_fractional":   true,
  "supports_notional_orders": true,
  "supports_extended_hours": true,
  "supports_short_selling": true,
  "supports_combo_types":  ["SINGLE", "OTO", "OCO", "OTOCO"]
}
```

Anything not listed above raises `UnsupportedCapability` at the
translator boundary — operators get a structured error rather than
a silent broker-side rejection.

## Closed roadmap items

| Item | Branch | Status |
|---|---|---|
| Dual-source auth (`BROKER_API_KEY` fallback + `ALPACA_LIVE_MODE`) | A | ✅ |
| Read-only `/v2/account` connectivity smoke | B | ✅ |
| README + capability docs | C / O | ✅ |
| Streaming WebSocket adapter (IEX feed; trades + quotes) | D | ✅ |
| Framework `instrument_sync` adapter | E | ✅ |
| `database/master_contract_db.py` conventional entrypoint | F | ✅ |
| `mapping/` directory in conventional layout | G | ✅ |
| Streaming reconnect-with-backoff + auto-resubscribe | H | ✅ |
| STOP / STOP_LIMIT / TRAILING_STOP order types | I | ✅ |
| IOC / FOK / OPG / ATC time-in-force + auction order types | J | ✅ |
| PRE_MARKET / POST_MARKET / EXTENDED sessions | K | ✅ |
| OCO / OTO / OTOCO bracket orders | L | ✅ |
| Crypto routing end-to-end (orders + streaming + sync) | M | ✅ |
| Inline maps consolidated under `mapping/transform_data.py` | N | ✅ |

## Known limits / out of scope

| Feature | Notes |
|---------|-------|
| Multi-leg options orders | Alpaca submits each option leg sequentially — no atomic combo for options spreads. |
| Level-2 market depth | Alpaca v2 data API is top-of-book only. Mode 4 subscriptions return `unsupported_capability`. |
| GTD time-in-force | Alpaca doesn't support GTD; operators wanting per-day cancellation use DAY (auto-expires) or GTC + manual cancel. |
| PDT enforcement (accounts < $25K) | Alpaca rejects on broker-side; OpenAlgo surfaces the error verbatim. No client-side PDT block. |
| SIP feed | Available via `ALPACA_STREAM_FEED=sip` but requires a paid Alpaca subscription. |
| Mixed equity + crypto in one streaming adapter | Alpaca uses one URL per asset family. Spawn two adapter instances. |

## Tests

```bash
# Unit (no network) — translator, mapping, sync, streaming, master-contract entrypoint
uv run pytest tests/broker/alpaca tests/api_v2/test_promoted_orders_alpaca.py \
              tests/api_v2/test_promoted_market_data_alpaca.py \
              tests/compliance/test_alpaca_compliance.py \
              tests/instrument_sync/test_alpaca_adapter.py -q

# Account smoke (paper, read-only — Branch B)
ALPACA_E2E=1 uv run pytest tests/e2e/test_alpaca_account_smoke.py -q

# Full E2E (paper, places + cancels a 1-share AAPL MARKET BUY)
ALPACA_E2E=1 uv run pytest tests/e2e/test_alpaca_smoke.py -q
```

## References

* [Alpaca Trading API docs](https://docs.alpaca.markets/reference/getorders)
* [Alpaca data API docs](https://docs.alpaca.markets/reference/stockquotes-1)
* [Alpaca crypto streaming docs](https://docs.alpaca.markets/docs/streaming-real-time-data)
* [OpenAlgo broker onboarding checklist](../../docs/refactor/future-broker-onboarding-checklist.md)
* [ADR 0005 — two-lane architecture](../../docs/adr/0005-two-lanes-legacy-and-promoted.md)
* [ADR 0023 — promoted-broker-only fields](../../docs/adr/0023-track-a-v4-overview.md)
* [ADR 0025 — strict-mode plugin schema](../../docs/adr/0025-strict-mode-plugin-schema.md)
