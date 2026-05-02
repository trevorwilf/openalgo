# Region plugin schema — v3 fields

Phase 0 of the market-agnostic refactor adds 10 optional fields to
`domain/regions.py` `MarketRegion`. All default to empty. No live
consumer reads them in Phase 0; they exist as the destination for the
relocated India data and the new US/EU/UK data that lands in later
phases.

## product_vocabulary

```python
product_vocabulary: dict[str, list[str]] = Field(default_factory=dict)
```

Region-allowed product codes per asset class. India example:

```json
{
  "EQUITY": ["MIS", "CNC", "NRML"],
  "FUTURE": ["NRML", "MIS"],
  "OPTION": ["NRML", "MIS"]
}
```

US example:

```json
{
  "EQUITY": ["DAY_TRADE", "OVERNIGHT"]
}
```

Phase 3 (T-20) consumes this in the 8 critical service entry points
to replace `VALID_PRODUCT_TYPES` from `utils/constants.py`.

## price_type_vocabulary

```python
price_type_vocabulary: dict[str, list[str]] = Field(default_factory=dict)
```

Region-allowed price types per asset class. India example:

```json
{
  "EQUITY": ["MARKET", "LIMIT", "SL", "SL-M"]
}
```

Phase 3 (T-20) consumes this to replace `VALID_PRICE_TYPES`.

## mandatory_close_rules

```python
mandatory_close_rules: list[dict[str, Any]] = Field(default_factory=list)
```

Auto-square-off rules. India example (data relocated by Phase 2 T-11):

```json
[
  {"venue": "NSE", "local_close": "15:15", "applies_to": ["MIS"]},
  {"venue": "BSE", "local_close": "15:15", "applies_to": ["MIS"]},
  {"venue": "CDS", "local_close": "16:45", "applies_to": ["MIS"]},
  {"venue": "BCD", "local_close": "16:45", "applies_to": ["MIS"]},
  {"venue": "MCX", "local_close": "23:30", "applies_to": ["MIS"]},
  {"venue": "NCDEX", "local_close": "17:00", "applies_to": ["MIS"]}
]
```

US example:

```json
[
  {"venue": "XNYS", "local_close": "16:00", "applies_to": ["DAY_TRADE"]}
]
```

## quantity_freeze_rules

```python
quantity_freeze_rules: list[dict[str, Any]] = Field(default_factory=list)
```

Per-(venue, instrument-family) qty-freeze rules. India example
(relocated by Phase 2 T-12):

```json
[
  {"venue": "NFO", "underlying": "NIFTY", "qty_freeze": 1800}
]
```

The US qty-freeze list is empty (no equivalent regulatory concept).

## currency_locale

```python
currency_locale: dict[str, str] = Field(default_factory=dict)
```

Per-currency BCP-47 locale tag for display formatting. Example:

```json
{"INR": "en-IN", "USD": "en-US", "EUR": "en-GB", "GBP": "en-GB"}
```

Phase 4 (T-16) consumes this on the frontend to replace the
hardcoded `INR/JPY/else-en-US` chain.

## option_grammar

```python
option_grammar: dict[str, Any] = Field(default_factory=dict)
```

Date format, right codes, and parsing regex hint. India example:

```json
{
  "date_format": "DDMMMYY",
  "right_codes": ["CE", "PE"],
  "regex_hint": "^[A-Z]+\\d{1,2}[A-Z]{3}\\d{2}\\d+\\.?\\d*[CP]E$"
}
```

US (OCC-21) example:

```json
{
  "date_format": "YYMMDD",
  "right_codes": ["CALL", "PUT"],
  "regex_hint": "^[A-Z\\s]{6}\\d{6}[CP]\\d{8}$"
}
```

Phase 2 (T-14) and Phase 7 (US options provider) consume this.

## index_classification

```python
index_classification: dict[str, list[str]] = Field(default_factory=dict)
```

Maps a venue to its index venue codes. India example:

```json
{"NSE": ["NSE_INDEX"], "BSE": ["BSE_INDEX"]}
```

Phase 5 (T-21) consumes this to drop the WS router substring match
on `"NSE"` / `"BSE"` / `"INDEX"`.

## legacy_compat_shim

```python
legacy_compat_shim: dict[str, Any] = Field(default_factory=dict)
```

Opaque marker for v1-lane attachment. Only India uses this today;
populated in Phase 9 (T-23) when the v1 lane is physically relocated
to `market_regions/india/legacy_v1/`.

## screener_providers

```python
screener_providers: list[str] = Field(default_factory=list)
```

Provider codes registered for the region's screener dispatcher.
India example:

```json
["chartink"]
```

Phase 8 (T-28) and Phase 7 use this to register and discover
providers.

## master_contract_refresh_policy

```python
master_contract_refresh_policy: dict[str, Any] = Field(default_factory=dict)
```

Refresh cadence/strategy for master contracts at the region level.
This is distinct from `BrokerCapabilities.master_contract_refresh_policy`,
which is the broker-level override. Region-level example:

```json
{
  "frequency": "daily",
  "anchor_local_time": "08:00",
  "skip_if_24x7": false
}
```

Phase 4 of v6 already wired the broker-level field; the region-level
version is added in Phase 0 for symmetry and future use.
