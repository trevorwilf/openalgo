"""LEGACY INDIA COMPATIBILITY — Indian exchange / product / price-type
vocabularies used by the v1 API and the existing 24+ India broker
adapters.

New code MUST NOT import ``VALID_EXCHANGES``, ``VALID_PRODUCT_TYPES``,
or ``VALID_PRICE_TYPES`` from this module. New non-India request
validation lives in ``domain/orders.py`` and the v2 endpoints under
``restx_api/v2/``. ADR 0017 formalizes the legacy stamp;
``tests/contracts/test_v1_schemas_classification.py`` enforces the
import block on classified PROMOTED_CORE files.

Reference: https://docs.openalgo.in/api-documentation/v1/order-constants
"""

# Sentinel read by ``scripts/audit/classify_files.py`` and the v1
# legacy-classification contract test. Do not remove.
LEGACY_INDIA_COMPATIBILITY = True

# Exchange Types
EXCHANGE_NSE = "NSE"  # NSE Equity
EXCHANGE_NFO = "NFO"  # NSE Futures & Options
EXCHANGE_CDS = "CDS"  # NSE Currency
EXCHANGE_BSE = "BSE"  # BSE Equity
EXCHANGE_BFO = "BFO"  # BSE Futures & Options
EXCHANGE_BCD = "BCD"  # BSE Currency
EXCHANGE_MCX = "MCX"  # MCX Commodity
EXCHANGE_NCDEX = "NCDEX"  # NCDEX Commodity
EXCHANGE_NSE_INDEX = "NSE_INDEX"  # NSE Index
EXCHANGE_BSE_INDEX = "BSE_INDEX"  # BSE Index
EXCHANGE_CRYPTO = "CRYPTO"  # Crypto Exchanges (broker-agnostic; brexchange carries broker name)

# Set of all crypto-family exchanges.
# Use `exchange in CRYPTO_EXCHANGES` instead of `exchange == "CRYPTO"` so that
# onboarding a second crypto exchange (e.g. BINANCE, BYBIT) is a one-line change here.
CRYPTO_EXCHANGES: set[str] = {EXCHANGE_CRYPTO}

# Set of broker names that map to crypto exchanges.
# Used to select the correct download cutoff timezone (UTC vs IST).
# Add new crypto brokers here — the smart download logic picks this up automatically.
CRYPTO_BROKERS: set[str] = {"deltaexchange"}

# Instrument type for crypto perpetual futures (used in symbol DB queries).
INSTRUMENT_PERPFUT: str = "PERPFUT"

# Default quote-currency suffix for crypto perpetual instruments.
# e.g. BTCUSDT = BTC + CRYPTO_QUOTE_CURRENCY — update here if/when USDC or INR is added.
CRYPTO_QUOTE_CURRENCY: str = "USDT"

# Set of all derivative-capable exchanges (FNO + Crypto).
# Use `exchange in FNO_EXCHANGES` instead of maintaining local sets in each service.
# Adding a new exchange family is a one-line change here.
FNO_EXCHANGES: set[str] = {
    EXCHANGE_NFO,
    EXCHANGE_BFO,
    EXCHANGE_MCX,
    EXCHANGE_CDS,
    EXCHANGE_BCD,
    EXCHANGE_NCDEX,
} | CRYPTO_EXCHANGES

# T-30 (v7 Phase 8): EXCHANGE_CRYPTO removed from India's
# VALID_EXCHANGES. Crypto is now its own region
# (``market_regions/crypto/``); Delta Exchange's
# ``supported_regions`` flipped to ``["crypto"]``. Indian brokers
# no longer claim crypto venues. Operators with legacy crypto data
# under India still see EXCHANGE_CRYPTO via CRYPTO_EXCHANGES /
# FNO_EXCHANGES; only the v1-validation list is trimmed.
VALID_EXCHANGES = [
    EXCHANGE_NSE,
    EXCHANGE_NFO,
    EXCHANGE_CDS,
    EXCHANGE_BSE,
    EXCHANGE_BFO,
    EXCHANGE_BCD,
    EXCHANGE_MCX,
    EXCHANGE_NCDEX,
    EXCHANGE_NSE_INDEX,
    EXCHANGE_BSE_INDEX,
]

# Product Types
PRODUCT_CNC = "CNC"  # Cash & Carry for equity
PRODUCT_NRML = "NRML"  # Normal for futures and options
PRODUCT_MIS = "MIS"  # Intraday Square off

VALID_PRODUCT_TYPES = [PRODUCT_CNC, PRODUCT_NRML, PRODUCT_MIS]

# Price Types
PRICE_TYPE_MARKET = "MARKET"  # Market Order
PRICE_TYPE_LIMIT = "LIMIT"  # Limit Order
PRICE_TYPE_SL = "SL"  # Stop Loss Limit Order
PRICE_TYPE_SLM = "SL-M"  # Stop Loss Market Order

VALID_PRICE_TYPES = [PRICE_TYPE_MARKET, PRICE_TYPE_LIMIT, PRICE_TYPE_SL, PRICE_TYPE_SLM]

# Order Actions
ACTION_BUY = "BUY"  # Buy
ACTION_SELL = "SELL"  # Sell

VALID_ACTIONS = [ACTION_BUY, ACTION_SELL]

# Exchange Badge Colors (for UI)
EXCHANGE_BADGE_COLORS = {
    EXCHANGE_NSE: "badge-accent",
    EXCHANGE_NFO: "badge-secondary",
    EXCHANGE_CDS: "badge-info",
    EXCHANGE_BSE: "badge-neutral",
    EXCHANGE_BFO: "badge-warning",
    EXCHANGE_BCD: "badge-error",
    EXCHANGE_MCX: "badge-primary",
    EXCHANGE_NCDEX: "badge-success",
    EXCHANGE_NSE_INDEX: "badge-accent",
    EXCHANGE_BSE_INDEX: "badge-neutral",
    EXCHANGE_CRYPTO: "badge-primary",
}

# Required Fields for Order Placement
REQUIRED_ORDER_FIELDS = ["apikey", "strategy", "symbol", "exchange", "action", "quantity"]

# Required Fields for Smart Order Placement
REQUIRED_SMART_ORDER_FIELDS = [
    "apikey",
    "strategy",
    "symbol",
    "exchange",
    "action",
    "quantity",
    "position_size",
]

# Required Fields for Cancel Order
REQUIRED_CANCEL_ORDER_FIELDS = ["apikey", "strategy", "orderid"]

# Required Fields for Cancel All Orders
REQUIRED_CANCEL_ALL_ORDER_FIELDS = ["apikey", "strategy"]

# Required Fields for Close Position
REQUIRED_CLOSE_POSITION_FIELDS = ["apikey", "strategy"]

# Required Fields for Modify Order
REQUIRED_MODIFY_ORDER_FIELDS = [
    "apikey",
    "strategy",
    "symbol",
    "action",
    "exchange",
    "orderid",
    "product",
    "pricetype",
    "price",
    "quantity",
    "disclosed_quantity",
    "trigger_price",
]

# Default Values for Optional Fields
DEFAULT_PRODUCT_TYPE = PRODUCT_MIS
DEFAULT_PRICE_TYPE = PRICE_TYPE_MARKET
DEFAULT_PRICE = "0"
DEFAULT_TRIGGER_PRICE = "0"
DEFAULT_DISCLOSED_QUANTITY = "0"
