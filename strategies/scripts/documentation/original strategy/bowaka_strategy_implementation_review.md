# Bowaka Strategy Implementation Review

**Date:** May 7, 2026  
**Scope:** Review of the uploaded Bowaka strategy markdowns, prefilter script, strategy script, YAML configs, Windows scheduler XML, and runbook.

## Verdict

The scripts implement a reasonable **Bowaka-like daily OHLCV scaffold**, but I would **not call it fully correct for live trading yet**.

The prefilter captures the main inferred signal family: **volume / participation**, **daily volatility or range state**, and **moving-average / trend confirmation**. That lines up with the Bowaka reconstruction that the strategy is likely a simple long-only OHLCV rule with roughly “one volume, one daily, and one moving-average” style filters inside small-cap or microcap names that are “in play.”

The live strategy also correctly consumes a candidate JSON file, submits long-only market-style entries, maintains state, handles time-stops and signal-fade exits, and includes kill-switch scaffolding.

The biggest gaps are not syntax-level. They are **trading-behavior mismatches and operational risks**:

- Bracket prices are based on the candidate’s prior close instead of the actual market-entry fill.
- There is no per-symbol ADV participation cap.
- All orders use `XNAS`, even though the prefilter allows NYSE, AMEX, ARCA, and BATS names.
- The strategy does not implement the finer intraday confirmation layer implied by the Bowaka writeup.
- A few risk and recovery paths can leave stale state or live broker orders not properly tracked.

Both Python files compile successfully under `py_compile`. I did **not** live-test the scripts against Alpaca or OpenAlgo endpoints.

---

## What is implemented well

### 1. The prefilter math is directionally aligned with the Bowaka thesis

The prefilter computes:

- prior-lookback average dollar volume,
- average volume,
- RVOL,
- ATR%,
- gap percent,
- range expansion,
- close location,
- EMA distance,
- EMA slope,
- and a simple signal-strength score.

That is a good implementation of the inferred Bowaka state:

> abnormal participation + abnormal daily movement + trend confirmation.

The filters then gate on price, ADV, RVOL, ATR%, range expansion, close location, EMA distance, and EMA slope. That is a reasonable first approximation of the markdown’s proposed feature family.

### 2. The two-file architecture is sensible

The architecture is clean:

1. A scheduled after-close prefilter scans the broad universe.
2. It writes `data/in_play_candidates.json`.
3. The OpenAlgo strategy reads that file at the next session open.
4. The live strategy handles entry, state, exits, reconciliation, and kill-switch behavior.

The Windows task XML also matches that design: it runs the prefilter after the U.S. market close on weekdays and writes candidates for the trading strategy to consume the next morning.

### 3. The strategy has a serious state and recovery skeleton

The strategy includes useful production-oriented pieces:

- atomic state writes,
- session-date reset,
- daily P&L baseline,
- candidate staleness checks,
- fill polling,
- time-stop exits,
- signal-fade exits,
- daily P&L circuit breaker,
- startup reconciliation,
- kill-switch levels,
- and daily summary logging.

That is a much better starting point than a one-off trading script.

### 4. The entry and exit style is broadly consistent with the inferred strategy

The strategy is long-only and market-entry oriented. It uses bracket-style target and stop exits, plus script-managed time-stop and signal-fade exits. That is directionally consistent with the Bowaka reconstruction: small-cap/microcap names, large expected move relative to spread, market-order preference, and capacity limits caused by market impact.

---

## Critical issues to fix before live trading

### 1. Bracket prices are based on the candidate close, not the actual entry fill

`submit_otoco()` computes:

```python
target = entry.close_price * (1 + target_pct)
stop   = entry.close_price * (1 - stop_pct)
```

But `entry.close_price` comes from the prefilter candidate, which is the prior daily close. The actual entry is a market buy at the next session. In small-cap and microcap names, the next open can gap dramatically.

Example:

- Candidate close: `$10.00`
- Target from config: `$11.50`
- Stop from config: `$9.20`
- Actual next-open fill: `$13.00`

In that case, the take-profit is now below the actual entry price, which can cause unintended behavior. The reverse problem can also happen if the next-open fill is far below the candidate close.

For this strategy, bracket levels should be based on the **actual fill price**, or at minimum a fresh open or quote snapshot.

A safer order flow would be:

1. Submit parent market buy.
2. Poll until the parent is filled.
3. Read `filled_avg_price`.
4. Submit OCO target and stop children based on that fill price.
5. Persist the real entry price and child order IDs.

If OpenAlgo or Alpaca supports a true bracket whose child levels can be derived server-side from the fill, use that. The current implementation sends fixed child prices up front.

---

### 2. All orders use `XNAS`, while the prefilter allows non-NASDAQ symbols

The prefilter universe allows:

```yaml
allowed_exchanges:
  - NASDAQ
  - NYSE
  - ARCA
  - AMEX
  - BATS
```

The strategy uses one fixed venue code:

```yaml
sizing:
  default_venue_code: XNAS
```

That means the prefilter can produce NYSE, AMEX, ARCA, or BATS names, but the strategy still submits every order using `XNAS`.

This is likely an instrument-mapping bug. Either restrict the prefilter to NASDAQ only:

```yaml
universe:
  allowed_exchanges: ["NASDAQ"]
```

or have the prefilter write a venue field into each candidate:

```json
{
  "ticker": "XYZ",
  "exchange": "NYSE",
  "venue_code": "XNYS"
}
```

Then submit orders using the candidate’s venue code rather than a global default.

This matters because the runbook says Alpaca instrument sync and broker maps must be populated for every ticker the prefilter can produce. If the prefilter can produce NYSE, AMEX, ARCA, or BATS symbols but the strategy submits all as `XNAS`, you will get avoidable mapping failures.

---

### 3. The strategy is missing the core market-impact sizing cap

The Bowaka markdowns repeatedly treat **market impact and capacity** as central to the edge. The strategy has:

```yaml
sizing:
  per_trade_pct: 0.10

risk:
  max_gross_exposure_pct: 0.50
  max_per_trade_dollars: null
```

But it does **not** cap each position as a fraction of that symbol’s average dollar volume, even though the candidate JSON includes `avg_dollar_volume`.

This is acceptable only for small accounts. For example:

- At `$100,000` equity, 10% is `$10,000`.
- With a `$250,000` ADV floor, that is 4% of ADV.
- At `$1,000,000` equity, 10% is `$100,000`.
- With the same `$250,000` ADV name, that is 40% of ADV.

That contradicts the capacity-limited thesis.

Add a cap such as:

```yaml
risk:
  max_position_as_adv_frac: 0.03
```

Then cap target notional during sizing:

```python
adv_cap = candidate.features["avg_dollar_volume"] * max_position_as_adv_frac
target_notional = min(
    equity * per_trade_pct,
    max_per_trade_dollars or float("inf"),
    adv_cap,
)
```

This is one of the most important strategy-fidelity fixes.

---

### 4. The current implementation is daily-next-open only, not the likely two-stage daily/intraday setup

The strongest architecture inference from the markdown is:

1. broad daily or hourly scan first,
2. then a more granular current-session trigger before entry.

Your implementation runs the prefilter after the close and enters once at the next session open. That means it trades:

> yesterday was in play, so buy the next open.

The inferred Bowaka workflow is closer to:

> this session is in play, then wait for a live confirmation.

The current version is still a valid prototype, but it is not the full inferred Bowaka behavior.

To align more closely, add an intraday confirmation layer before submitting entries, such as:

```text
daily candidate
+ first 5–30 minute opening-range RVOL
+ price above VWAP or short EMA
+ no failure below opening range
+ spread/liquidity sanity check
+ current halt / tradability check
```

This would reduce the risk of buying prior-day runners that are already exhausted.

---

### 5. Candidate freshness can be wrong on holidays or failed data days

`write_output()` sets:

```python
"as_of_date": now_utc.date().isoformat()
```

That is the run date, not necessarily the date of the latest daily bar used.

This can be wrong if:

- the task runs on a market holiday,
- Alpaca has not published the latest daily bar yet,
- the script is run manually on a weekend,
- or the data pull silently returns older bars.

Fix this by deriving `as_of_date` from the **latest bar timestamp actually used**:

```python
latest_bar_ts = features["timestamp"].max()
as_of_date = latest_bar_ts.tz_convert("America/New_York").date().isoformat()
```

Also consider refusing to overwrite the prior candidates file when the latest bar date is not the expected latest NYSE trading day.

---

### 6. IEX feed is risky for this signal family

The prefilter config uses:

```yaml
alpaca:
  feed: "iex"
```

For a strategy based on RVOL, ADV, ATR%, and range expansion in microcaps, partial feed coverage can materially distort the signal. IEX may be acceptable for prototyping, but production candidate selection should compare IEX versus SIP on the exact names your scanner produces.

This is especially important because the strategy’s core signal is volume-sensitive.

---

## Important code-level bugs and recovery risks

### 1. `run_session_entry_pass()` marks the session as done before candidate validation succeeds

The strategy does this:

```python
equity = fetch_equity(...)
reset_for_new_session(...)
save_state(...)
cands = load_candidates(...)
```

If candidate loading fails because the file is stale, missing, or hash-mismatched, the function returns after `state["session_date"]` has already been set to today.

On later ticks that same day, the strategy will not retry the entry pass.

A safer order is:

```python
equity = fetch_equity(...)
cands = load_candidates(...)
reset_for_new_session(...)
save_state(...)
select and submit entries
```

If candidates fail validation, do not mark the session as processed.

---

### 2. Prefilter and strategy gates are duplicated, and the handshake is disabled

The uploaded configs have matching gates:

- `rvol_min: 1.5`
- `atr_pct_min: 0.06`
- `range_expansion_min: 1.25`
- `close_location_min: 0.6`
- `ema_distance_min: 0.0`
- `ema_slope_min: 0.0`

But the strategy config has:

```yaml
prefilter_handshake:
  expected_config_hash: null
```

So the strategy accepts any prefilter config hash.

In live use, either pin the expected prefilter hash or load the prefilter config at strategy startup and compare the signal gates and indicators.

Otherwise, the prefilter thresholds can drift while the strategy’s signal-fade exits continue using different thresholds.

---

### 3. Exit market-sell failures can be marked as `exiting` anyway

`submit_market_sell()` returns parsed JSON with `_http_status`, but `trigger_time_stop()` does not validate that the order was accepted.

It marks:

```python
pos["status"] = "exiting"
pos["exit_order_id"] = exit_id
```

even if the sell returned a 4xx or 5xx error and `exit_id` is empty.

That can strand a position in `status="exiting"` and prevent retry attempts.

Fix by checking status and order ID before mutating state:

```python
resp = submit_market_sell(...)
if resp.get("_http_status") not in (200, 201):
    LOG.error("exit sell rejected ...")
    return  # keep status="filled" so the next pass retries
```

---

### 4. L3 hard-kill does not cancel pending parent orders

`execute_kill_l2()` handles pending positions by canceling parent and child orders.

`execute_kill_l3()` only calls `trigger_time_stop()` for positions with:

```python
status == "filled"
```

Pending parent orders are not canceled before the strategy exits with code `99`.

For a hard kill, L3 should do at least everything L2 does, then exit.

---

### 5. L2 can drop state even if cancel fails

For pending positions, `execute_kill_l2()` logs cancel exceptions but still removes the position from state:

```python
state["open_positions"].pop(ticker, None)
```

If the cancel failed and the broker order remains live, the strategy loses tracking.

Only drop the position after confirmed cancel or terminal order status. Otherwise, keep it with a `cancel_failed` or `needs_reconcile` marker.

---

### 6. Fill polling checks canonical fill status for parents, but not for child or exit orders

For parent fills, the code checks:

```python
if status in _FILLED or canonical == "FILLED":
```

For target, stop, and exit fills, it only checks:

```python
if status in _FILLED:
```

If OpenAlgo gives an adapter-specific raw status but `canonical_status == "FILLED"`, child or exit fills may not close positions.

Use the same canonical check for child and exit orders.

---

### 7. Startup reconciliation does not surface untracked broker positions when state is empty

The runbook says that if `state.json` is moved aside, reconciliation will surface untracked broker positions.

But the code returns early when state is empty:

```python
if not open_positions and not pending_signal_fade_exits:
    LOG.info("reconciliation: empty state, fresh start")
    return summary
```

That means a clean or reset state will **not** fetch broker positions and will not warn about untracked live positions.

Remove that early return. Always fetch broker positions at startup.

---

### 8. Daily summary `count_opened` is not actually “opened today”

`write_session_summary()` sets:

```python
"count_opened": len(state.get("open_positions") or {})
```

That is the number of currently open positions at summary time, not the number opened during the session.

It excludes trades that opened and closed intraday, and it can include carryover positions.

If you want a true `count_opened`, write an explicit entry record to `daily_summary.jsonl` at order submission or parent fill, then count today’s entry records.

---

## Strategy-fidelity gaps that are not necessarily bugs

### 1. No market cap, float, split, financing, catalyst, or halt-risk enrichment

The current prefilter is purely OHLCV and exchange/price/ADV based. That is acceptable for a minimal implementation because the Bowaka thesis emphasizes a simple OHLCV signal.

However, the markdown also discusses structural context: reverse splits, financings, low float, halts, and hype windows. Those are not required for the first version, but they would be useful as research or risk-control enrichments.

A good compromise is to keep the live entry rule OHLCV-only, but add optional metadata fields to the candidate file:

```json
{
  "ticker": "XYZ",
  "venue_code": "XNAS",
  "recent_reverse_split": true,
  "recent_financing": false,
  "halt_risk_tag": "medium",
  "float_shares": 1234567
}
```

Those fields can be used for diagnostics, sizing, or manual review without contaminating the simple entry rule.

---

### 2. ATR includes the current bar

The prefilter computes ATR using a rolling window that includes the current bar’s true range.

For an after-close next-open system, this is not lookahead. But for a true same-session scanner, you would usually compare today’s range against **prior ATR**, so the expansion gate is not diluted by the move it is trying to detect.

For a same-session implementation, prefer:

```python
prior_atr = tr.groupby(symbol).transform(lambda s: s.shift(1).rolling(atr_n).mean())
range_expansion = current_range / prior_atr
```

---

### 3. The system only enters once per session

Bowaka’s public description suggests that the anomaly can appear several times per day after a first filtering layer.

The current implementation enters only once at the first session tick. That is simpler and safer, but less faithful to the inferred architecture.

A closer implementation would allow:

- one premarket or post-close candidate scan,
- intraday confirmation checks,
- multiple entry windows,
- and per-symbol cooldowns to avoid repeated chasing.

---

### 4. Halt detection exists but is not fully wired into runtime behavior

The strategy includes `_is_halt_signal()`, and the runbook describes halt detection as a Phase 4 component.

However, the runtime path mostly relies on order rejection and `halt_skip_today`. For microcaps, this is a real operational risk.

At minimum, halt or pending-review status should:

- block new entries,
- prevent repeated order attempts,
- trigger operator-visible logging,
- and avoid marking a failed exit as completed.

---

## Minimal fix list

I would apply these changes before live trading:

1. Add per-candidate `venue_code`, or restrict the universe to NASDAQ only.
2. Stop using previous close for OTOCO bracket prices; base exits on actual fill.
3. Add `max_position_as_adv_frac` sizing.
4. Derive candidate `as_of_date` from the latest bar timestamp, not the run date.
5. Move `reset_for_new_session()` until after candidates validate.
6. Validate market-sell responses before marking positions as `exiting`.
7. Make L3 cancel pending orders too.
8. Do not drop L2 pending-order state unless cancel is confirmed.
9. Use canonical fill status checks for target, stop, and exit orders.
10. Always fetch broker positions during startup reconciliation.
11. Pin or auto-compare prefilter and strategy gates.
12. Fix `count_opened` so it tracks actual entries opened during the session.

After those changes, this would be a solid **Bowaka-inspired daily prefilter plus next-open execution system**.

To make it closer to the markdown’s inferred Bowaka strategy, the next major enhancement would be a **live intraday confirmation layer** before entry.

---

## Suggested implementation patches

### Add an ADV participation cap

Config:

```yaml
risk:
  max_position_as_adv_frac: 0.03
```

Sizing logic:

```python
def compute_qty(
    equity: float,
    close_price: float,
    per_trade_pct: float,
    max_per_trade_dollars: float | None = None,
    avg_dollar_volume: float | None = None,
    max_position_as_adv_frac: float | None = None,
) -> int:
    target = equity * per_trade_pct

    if max_per_trade_dollars is not None:
        target = min(target, max_per_trade_dollars)

    if avg_dollar_volume is not None and max_position_as_adv_frac is not None:
        target = min(target, avg_dollar_volume * max_position_as_adv_frac)

    if close_price <= 0 or target <= 0:
        return 0

    return int(math.floor(target / close_price))
```

---

### Add venue code to candidates

Prefilter candidate row:

```python
d = {
    "ticker": sym,
    "exchange": row.get("exchange"),
    "venue_code": exchange_to_venue(row.get("exchange")),
}
```

Example mapping:

```python
EXCHANGE_TO_VENUE = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
    "ARCA": "ARCX",
    "BATS": "BATS",
}
```

Strategy candidate dataclass:

```python
@dataclass
class Candidate:
    ticker: str
    close: float
    signal_strength: float
    venue_code: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
```

Then use:

```python
venue_code = entry.candidate.venue_code or cfg["sizing"]["default_venue_code"]
```

---

### Prevent session-date lockout after candidate failure

Current risky order:

```python
equity = fetch_equity(...)
reset_for_new_session(state, today_et.isoformat(), equity)
save_state(state, state_path)
cands = load_candidates(...)
```

Safer order:

```python
equity = fetch_equity(...)
cands = load_candidates(...)
reset_for_new_session(state, today_et.isoformat(), equity)
save_state(state, state_path)
```

This way, stale or missing candidates do not permanently block that day’s entry pass.

---

### Validate market-sell acceptance before changing state

Current risk:

```python
resp = submit_market_sell(...)
exit_id = data.get("order_id") or data.get("id") or ""
pos["status"] = "exiting"
pos["exit_order_id"] = exit_id
```

Safer logic:

```python
resp = submit_market_sell(...)
status = resp.get("_http_status")
if status not in (200, 201):
    LOG.error("market sell rejected for %s: %s", ticker, resp)
    return

data = resp.get("data") or {}
exit_id = data.get("order_id") or data.get("id") or ""
if not exit_id:
    LOG.error("market sell accepted but no exit order id for %s: %s", ticker, resp)
    return

pos["status"] = "exiting"
pos["exit_order_id"] = exit_id
```

---

## Final assessment

The implementation is **directionally correct as a Bowaka-inspired prototype**, especially on the prefilter side. It captures the right broad feature family and has a serious state/risk scaffold.

However, it is **not yet safe enough for unattended live trading** because several edge cases can distort orders, sizing, venue routing, or recovery state.

The highest-priority conceptual fixes are:

1. fill-based brackets,
2. ADV participation sizing,
3. correct venue routing,
4. better candidate freshness,
5. stronger state recovery,
6. and intraday confirmation if the goal is to match the inferred Bowaka strategy more closely.
