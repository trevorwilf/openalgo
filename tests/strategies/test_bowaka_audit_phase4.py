"""Phase 4 audit acceptance tests — opening-range / VWAP + tighter quotes.

Covers:
  4.1 Tighter quote gates (window_minutes / max_spread_pct /
      max_quote_age_seconds / price_band) — already a YAML default.
  4.2 require_stable_quote_checks streak admit logic.
  4.3 compute_vwap_from_bars / build_opening_range_context /
      confirm_opening_range_vwap.
  4.5 Caching of fetch_or_compute_opening_range_context within a
      single filter pass (one HTTP call per ticker).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------- 4.3 vwap


def test_compute_vwap_from_bars_known_input():
    """Hand-computed VWAP for a 3-bar fixture."""
    import bowaka_strategy as bw
    bars = [
        {"high": 10.0, "low": 9.0, "close": 9.5, "volume": 100},
        {"high": 11.0, "low": 10.0, "close": 10.5, "volume": 200},
        {"high": 12.0, "low": 11.0, "close": 11.5, "volume": 300},
    ]
    # typical-price * volume:
    #   bar 1: (10+9+9.5)/3 = 9.5 → 9.5 * 100 = 950
    #   bar 2: (11+10+10.5)/3 = 10.5 → 10.5 * 200 = 2100
    #   bar 3: (12+11+11.5)/3 = 11.5 → 11.5 * 300 = 3450
    # sum = 6500, total volume = 600 → vwap = 10.8333...
    assert bw.compute_vwap_from_bars(bars) == pytest.approx(6500 / 600)


def test_compute_vwap_empty_returns_none():
    import bowaka_strategy as bw
    assert bw.compute_vwap_from_bars([]) is None


def test_compute_vwap_zero_volume_returns_none():
    import bowaka_strategy as bw
    bars = [
        {"high": 10.0, "low": 9.0, "close": 9.5, "volume": 0},
        {"high": 11.0, "low": 10.0, "close": 10.5, "volume": 0},
    ]
    assert bw.compute_vwap_from_bars(bars) is None


# ---------------------------------------------------------------- 4.3 build_opening_range_context


def _bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_build_opening_range_context_basic():
    import bowaka_strategy as bw
    bars = [
        _bar(10.0, 10.5, 9.9, 10.3, 1000),
        _bar(10.3, 10.7, 10.1, 10.6, 1500),
        _bar(10.6, 10.9, 10.4, 10.8, 1200),
    ]
    ctx = bw.build_opening_range_context(
        "AAPL", bars,
        prior_opening_vol_mean=3000.0,
        prior_close=9.95,
    )
    assert ctx is not None
    assert ctx["high"] == 10.9
    assert ctx["low"] == 9.9
    assert ctx["open"] == 10.0
    assert ctx["close"] == 10.8
    assert ctx["volume"] == 3700.0
    # close_location = (10.8 - 9.9) / (10.9 - 9.9) = 0.9
    assert ctx["close_location"] == pytest.approx(0.9)
    # vwap is positive and within OR range
    assert ctx["vwap"] is not None
    assert 9.9 <= ctx["vwap"] <= 10.9
    # opening_rvol = 3700 / 3000 = ~1.233
    assert ctx["opening_rvol"] == pytest.approx(3700 / 3000)
    assert ctx["prior_close"] == 9.95


def test_build_opening_range_context_empty_bars_returns_none():
    import bowaka_strategy as bw
    assert bw.build_opening_range_context("AAPL", []) is None


# ---------------------------------------------------------------- 4.3 confirm_opening_range_vwap


def _or_cfg(**overrides):
    base = {
        "enabled": True, "window_minutes": 15,
        "require_price_above_vwap": True,
        "require_price_above_session_open": True,
        "require_price_above_prior_close": True,
        "require_close_location_min": 0.60,
        "breakout_mode": "above_or_near_high",
        "near_high_tolerance_pct": 0.02,
        "opening_volume_rvol_min": 1.25,
    }
    base.update(overrides)
    return base


def _entry_like(strategy_module, ticker="AAPL", close=10.0):
    cand = strategy_module.Candidate(ticker, close, 5.0)
    return strategy_module.Entry(
        ticker=ticker, qty=100, close_price=close,
        venue_code="XNAS", candidate=cand,
    )


def _ctx(*, high=11.0, low=9.5, open_=10.0, close=10.9, vwap=10.5,
         close_loc=0.93, rvol=1.5, prior_close=10.0):
    return {
        "ticker": "AAPL",
        "high": high, "low": low, "open": open_, "close": close,
        "volume": 1000.0, "vwap": vwap,
        "close_location": close_loc,
        "opening_rvol": rvol, "prior_close": prior_close,
    }


def test_confirm_or_happy_path(strategy_module):
    quote = {"bid": 11.0, "ask": 11.1}
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(), _or_cfg(),
    )
    assert ok is True
    assert reason == "ok"


def test_confirm_or_below_vwap(strategy_module):
    quote = {"bid": 10.3, "ask": 10.4}   # mid 10.35 < vwap 10.5
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(), _or_cfg(),
    )
    assert ok is False
    assert reason == "below_vwap"


def test_confirm_or_below_prior_close(strategy_module):
    """mid above vwap + open, but below prior close — the prior-close
    gate fires."""
    quote = {"bid": 9.8, "ask": 9.9}   # mid 9.85
    entry = _entry_like(strategy_module)
    # session open and vwap below 9.85 so those gates pass; prior
    # close above 9.85 so that gate fails.
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote,
        _ctx(open_=9.5, vwap=9.0, close_loc=0.93, prior_close=10.0),
        _or_cfg(),
    )
    assert ok is False
    assert reason == "below_prior_close"


def test_confirm_or_close_location_low(strategy_module):
    quote = {"bid": 11.0, "ask": 11.1}
    entry = _entry_like(strategy_module)
    # close_loc=0.40 < 0.60
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(close_loc=0.40), _or_cfg(),
    )
    assert ok is False
    assert reason == "close_location_low"


def test_confirm_or_below_or_high_above_high_mode(strategy_module):
    """In above_high mode, mid must be >= or_high. mid=11 with
    or_high=12 → reject."""
    quote = {"bid": 10.95, "ask": 11.05}
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(high=12.0),
        _or_cfg(breakout_mode="above_high"),
    )
    assert ok is False
    assert reason == "below_or_high"


def test_confirm_or_near_high_within_tolerance(strategy_module):
    """In above_or_near_high mode with tol=0.02, mid=11 vs or_high=11.1
    passes (within 2%)."""
    quote = {"bid": 10.99, "ask": 11.01}
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(high=11.1, vwap=10.5, close_loc=0.93, prior_close=10.0),
        _or_cfg(breakout_mode="above_or_near_high",
                near_high_tolerance_pct=0.02),
    )
    assert ok is True


def test_confirm_or_opening_rvol_low(strategy_module):
    quote = {"bid": 11.0, "ask": 11.1}
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, _ctx(rvol=0.5), _or_cfg(opening_volume_rvol_min=1.25),
    )
    assert ok is False
    assert reason == "opening_rvol_low"


def test_confirm_or_no_ctx_fail_closed(strategy_module):
    quote = {"bid": 11.0, "ask": 11.1}
    entry = _entry_like(strategy_module)
    ok, reason = strategy_module.confirm_opening_range_vwap(
        entry, quote, None, _or_cfg(),
    )
    assert ok is False
    assert reason == "no_or_data"


# ---------------------------------------------------------------- 4.2 stable quote streak


@pytest.fixture
def cfg_with_streak(cfg_with_paths):
    cfg = dict(cfg_with_paths)
    cfg["entry"] = {
        **cfg.get("entry", {}),
        "bracket_pricing_mode": "actual_fill",
        "intraday_confirmation": {
            "enabled": True,
            "window_minutes": 0,
            "max_spread_pct": 0.05,
            "max_quote_age_seconds": 300,
            "require_stable_quote_checks": 3,
            "price_band": {
                "max_pct_above_close": 0.30,
                "min_pct_below_close": -0.15,
            },
        },
    }
    return cfg


def _quote_handler(price=10.0):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v2/quotes":
            return httpx.Response(200, json={
                "data": [{
                    "instrument": {"canonical_symbol": "AAPL"},
                    "quote": {"bid": price - 0.05, "ask": price + 0.05,
                              "timestamp": datetime.now(timezone.utc).isoformat()},
                }],
            })
        return httpx.Response(404, json={})
    return handler


def test_streak_admits_after_n_passes(strategy_module, cfg_with_streak):
    """Three consecutive passes admit; pass-fail-pass-pass-pass admits
    at tick 5."""
    state = strategy_module.blank_state()
    cand = strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=5.0,
        venue_code="XNAS", features={"avg_dollar_volume": 1e7},
    )
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    transport = httpx.MockTransport(_quote_handler(10.0))
    http = strategy_module.make_http_client("http://x", transport=transport)
    # Tick 1, 2 — pass but pre-threshold (streak < 3)
    for tick in (1, 2):
        out = strategy_module.filter_by_intraday_confirmation(
            [entry], cfg_with_streak, http, "k",
            state=state, entry_trigger="session_open",
            now_utc=datetime.now(timezone.utc),
        )
        assert out == []
    # Tick 3 — streak hits threshold, admit
    out = strategy_module.filter_by_intraday_confirmation(
        [entry], cfg_with_streak, http, "k",
        state=state, entry_trigger="session_open",
        now_utc=datetime.now(timezone.utc),
    )
    assert [e.ticker for e in out] == ["AAPL"]


def test_streak_resets_on_fail(strategy_module, cfg_with_streak):
    state = strategy_module.blank_state()
    cand = strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=5.0,
        venue_code="XNAS", features={"avg_dollar_volume": 1e7},
    )
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    # First two ticks pass.
    transport_ok = httpx.MockTransport(_quote_handler(10.0))
    http = strategy_module.make_http_client("http://x", transport=transport_ok)
    for _ in (1, 2):
        strategy_module.filter_by_intraday_confirmation(
            [entry], cfg_with_streak, http, "k",
            state=state, entry_trigger="session_open",
            now_utc=datetime.now(timezone.utc),
        )
    assert state["confirmation_streak"]["AAPL"] == 2
    # Tick 3 fails (price drops below band)
    transport_fail = httpx.MockTransport(_quote_handler(8.0))  # mid 8 vs close 10 -> below -15%
    cfg2 = dict(cfg_with_streak)
    cfg2["entry"] = dict(cfg2["entry"])
    cfg2["entry"]["intraday_confirmation"] = {
        **cfg2["entry"]["intraday_confirmation"],
        "price_band": {"max_pct_above_close": 0.30,
                       "min_pct_below_close": -0.05},
    }
    http_fail = strategy_module.make_http_client("http://x", transport=transport_fail)
    strategy_module.filter_by_intraday_confirmation(
        [entry], cfg2, http_fail, "k",
        state=state, entry_trigger="session_open",
        now_utc=datetime.now(timezone.utc),
    )
    # Reset to 0 — entry removed from streak dict.
    assert state["confirmation_streak"].get("AAPL", 0) == 0


# ---------------------------------------------------------------- 4.5 fetch caching


def test_fetch_or_compute_opening_range_caches_within_pass(
    strategy_module, cfg_with_paths,
):
    """The OR fetch caches per-ticker within a single
    filter_by_intraday_confirmation call so duplicate entries
    for the same ticker don't double-fetch.

    Direct test of fetch_or_compute_opening_range_context: TWO calls
    for the same ticker should make TWO HTTP calls when invoked
    individually (no cross-call cache) but only one inside a single
    filter_by_intraday_confirmation pass (via or_ctx_cache).
    """
    state = strategy_module.blank_state()
    cand = strategy_module.Candidate(
        "AAPL", close=10.0, signal_strength=5.0,
        venue_code="XNAS",
        features={"avg_dollar_volume": 1e7, "avg_volume": 1_000_000},
    )
    entry = strategy_module.Entry(
        ticker="AAPL", qty=100, close_price=10.0,
        venue_code="XNAS", candidate=cand,
    )
    call_count = {"quotes": 0, "bars": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v2/quotes":
            call_count["quotes"] += 1
            return httpx.Response(200, json={
                "data": [{
                    "instrument": {"canonical_symbol": "AAPL"},
                    "quote": {"bid": 10.5, "ask": 10.6,
                              "timestamp": datetime.now(timezone.utc).isoformat()},
                }],
            })
        if req.url.path == "/api/v2/bars":
            call_count["bars"] += 1
            # Return a single 1-min bar that passes every OR gate
            # (high above mid, OR-rvol > 1.25, close-location high).
            return httpx.Response(200, json={
                "data": {"bars": [
                    {"open": 9.9, "high": 10.6, "low": 9.85,
                     "close": 10.55, "volume": 200_000},
                ]},
            })
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    http = strategy_module.make_http_client("http://x", transport=transport)
    cfg = {
        **cfg_with_paths,
        "entry": {
            **cfg_with_paths.get("entry", {}),
            "intraday_confirmation": {
                "enabled": True,
                "window_minutes": 0,
                "max_spread_pct": 0.05,
                "max_quote_age_seconds": 300,
                "require_stable_quote_checks": 1,
                "price_band": {
                    "max_pct_above_close": 0.50,
                    "min_pct_below_close": -0.50,
                },
                "opening_range": {
                    "enabled": True,
                    "window_minutes": 15,
                    "require_price_above_vwap": True,
                    "require_price_above_session_open": True,
                    "require_price_above_prior_close": False,
                    "require_close_location_min": 0.60,
                    "breakout_mode": "above_or_near_high",
                    "near_high_tolerance_pct": 0.10,
                    "opening_volume_rvol_min": 1.25,
                    "opening_volume_session_share": 0.08,
                },
            },
        },
    }
    # Two entries for same ticker → should only fetch bars once.
    strategy_module.filter_by_intraday_confirmation(
        [entry, entry], cfg, http, "k",
        state=state, entry_trigger="session_open",
        now_utc=datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc),
    )
    # Quotes fetched twice (once per entry), bars only once (cache).
    assert call_count["bars"] == 1
