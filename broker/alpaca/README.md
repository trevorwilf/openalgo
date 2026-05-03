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
| Market families | `US_STOCK` |
| Asset classes | `EQUITY`, `ETF` (options/crypto: roadmap) |
| Auth style | API key + secret in HTTP headers (no OAuth) |
| Settlement | T+1 (equities; effective May 28, 2024) |
| Sessions | Regular (09:30–16:00 ET); pre/post-market roadmap |
| Quantity units | Whole, fractional, notional |
| Order types | MARKET, LIMIT (STOP / STOP_LIMIT / TRAILING_STOP roadmap) |
| Time-in-force | DAY, GTC (OPG / ATC / IOC / FOK roadmap) |
| Fractional shares | ✅ |
| Notional orders | ✅ |
| Short selling | ✅ (subject to Alpaca's `shortable` flag per asset) |
| Crypto | roadmap (24/7) |

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

## Endpoints

| Mode | REST base | Streaming base | Data base |
|------|-----------|----------------|-----------|
| Paper | `https://paper-api.alpaca.markets` | `wss://paper-api.alpaca.markets/stream` | `https://data.alpaca.markets` |
| Live | `https://api.alpaca.markets` | `wss://api.alpaca.markets/stream` | `https://data.alpaca.markets` |

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
├── api/
│   ├── auth_api.py          AlpacaAuth + authenticate() + load_credentials()
│   ├── order_api.py         AlpacaOrderTranslator (BrokerOrderTranslator)
│   ├── quote_api.py         AlpacaQuoteAdapter (latest quotes)
│   ├── bar_api.py           AlpacaBarAdapter (historical bars)
│   └── account_api.py       get_account_snapshot() (normalized funds shape)
└── sync/
    ├── instrument_sync.py   /v2/assets → instruments_repo (canonical)
    └── seed_rules.py        seeds Alpaca-specific BrokerRules entries
```

The promoted-lane translator registration happens automatically when
the framework imports `broker/alpaca/`; orders flow through
`AlpacaOrderTranslator` for capability validation + native-payload
build, then to Alpaca's `POST /v2/orders`.

## Capabilities (per `plugin.json`)

```json
{
  "supported_regions":     ["us"],
  "market_families":       ["US_STOCK"],
  "supported_venue_codes": ["XNAS", "XNYS", "ARCX", "BATS"],
  "supported_asset_classes":["EQUITY", "ETF"],
  "supported_order_types": ["MARKET", "LIMIT"],
  "supported_time_in_force":["DAY", "GTC"],
  "supported_sessions":    ["REGULAR"],
  "supports_fractional":   true,
  "supports_notional_orders": true,
  "supports_short_selling": true
}
```

Anything not listed above raises `UnsupportedCapability` at the
translator boundary — operators get a structured error rather than
a silent broker-side rejection.

## Known limits / roadmap

| Feature | Status |
|---------|--------|
| Extended-hours session (pre / post-market) | declared `false`; roadmap |
| OCO / OTO / OTOCO bracket orders | not declared; roadmap |
| Multi-leg options orders | declared `false`; Alpaca submits legs sequentially, no atomic combo |
| Crypto (BTC/USD etc.) | manifest covers SPOT asset class; routing roadmap |
| Live WebSocket tick stream | streaming adapter scaffolding lives in `streaming/` (Branch D) |
| Master-contract scheduler integration | `services/instrument_sync_adapters/alpaca_adapter.py` (Branch E) |
| `database/master_contract_db.py` conventional entrypoint | Branch F |
| `mapping/` directory in conventional layout | Branch G |
| Level-2 depth ladder | not available — Alpaca v2 data API is top-of-book only |
| PDT enforcement (accounts < $25K) | passed through — Alpaca rejects, OpenAlgo surfaces the error verbatim |

## Tests

```bash
# Unit (no network)
uv run pytest tests/broker/alpaca tests/api_v2/test_promoted_orders_alpaca.py \
              tests/api_v2/test_promoted_market_data_alpaca.py \
              tests/compliance/test_alpaca_compliance.py -q

# Account smoke (paper, read-only)
ALPACA_E2E=1 uv run pytest tests/e2e/test_alpaca_account_smoke.py -q

# Full E2E (paper, places + cancels a 1-share AAPL MARKET BUY)
ALPACA_E2E=1 uv run pytest tests/e2e/test_alpaca_smoke.py -q
```

## References

* [Alpaca Trading API docs](https://docs.alpaca.markets/reference/getorders)
* [OpenAlgo broker onboarding checklist](../../docs/refactor/future-broker-onboarding-checklist.md)
* [ADR 0005 — two-lane architecture](../../docs/adr/0005-two-lanes-legacy-and-promoted.md)
* [ADR 0023 — promoted-broker-only fields](../../docs/adr/0023-track-a-v4-overview.md)
* [ADR 0025 — strict-mode plugin schema](../../docs/adr/0025-strict-mode-plugin-schema.md)
