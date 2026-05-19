#!/usr/bin/env python3
"""Bowaka v2 — pure-function feature module.

Implements the formula specification from
``strategies/scripts/documentation/V2/bowaka_v2_quant_engineering_handoff.md``
Appendix B. No I/O. No globals. No dependence on the strategy module.

This module is the **single source of truth** for v2 feature
computation. The scanner, the backtester, the signal-fade exit
evaluator, and any analysis notebook must all import from here. Any
divergence breaks the feature-parity contract pinned in Phase 5's
``test_scanner_and_backtester_produce_identical_features``.

Causality (handoff §5.7 + Appendix B):
- prior_atr_14d / avg_volume_20d / avg_dollar_volume_20d / ema_10_prior
  are computed from **completed** daily bars only — the input frame
  MUST end on the prior session. Functions enforce this by indexing
  from the tail.
- Forming-session features use minute bars up to the scan time ``t``;
  bars at or beyond ``t+1`` minute must not move the result.
- Volume curve is causal: it is built from prior sessions only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- prior baselines


def compute_prior_daily_baselines(
    daily_bars_df: pd.DataFrame,
    *,
    atr_n: int = 14,
    lookback: int = 20,
    ema_n: int = 10,
    ema_slope_lookback: int = 3,
) -> dict[str, float | None]:
    """Compute the prior-daily baselines used by the v2 scanner /
    backtester.

    ``daily_bars_df`` must contain columns ``open``, ``high``,
    ``low``, ``close``, ``volume`` (case-insensitive), sorted in
    ascending chronological order, and END at the **prior completed
    session**. Callers are responsible for slicing the frame to
    exclude today's forming bar before invoking this function — the
    handoff §5.7 lookahead rule says ATR / volume / EMA baselines
    must not see the current session.

    Returns a dict with the eight baseline fields. When the frame is
    too short (fewer than ``atr_n + 1`` rows for ATR, fewer than
    ``lookback`` rows for volume / dollar_volume averages, fewer than
    ``ema_n + ema_slope_lookback`` rows for EMA), the corresponding
    field is ``None``.
    """
    if daily_bars_df is None or len(daily_bars_df) == 0:
        return _empty_baselines()

    df = daily_bars_df.copy()
    df.columns = [c.lower() for c in df.columns]
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        return _empty_baselines()

    # ATR — Wilder's true range averaged over the last `atr_n` rows.
    df["prev_close"] = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"]  - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    if len(tr) >= atr_n + 1:
        prior_atr_14d = float(tr.iloc[-atr_n:].mean())
    else:
        prior_atr_14d = None

    prior_close = float(df["close"].iloc[-1]) if len(df) > 0 else None
    prior_atr_pct = (
        prior_atr_14d / prior_close
        if (prior_atr_14d is not None and prior_close and prior_close > 0)
        else None
    )

    if len(df) >= lookback:
        avg_volume_20d = float(df["volume"].iloc[-lookback:].mean())
        avg_dollar_volume_20d = float(
            (df["close"].iloc[-lookback:] * df["volume"].iloc[-lookback:]).mean()
        )
    else:
        avg_volume_20d = None
        avg_dollar_volume_20d = None

    # EMA — pandas adjust=False gives the same recursion as the
    # classic "alpha = 2 / (n+1)" Wilder-style EMA.
    if len(df) >= ema_n + ema_slope_lookback:
        ema_series = df["close"].ewm(span=ema_n, adjust=False).mean()
        ema_10_prior = float(ema_series.iloc[-1])
        # ema_10_lag_3 = EMA value `ema_slope_lookback` rows back.
        # Handoff Appendix B: `ema_10_lag_3 = ema(close, span=10)[-4]`
        # with default ema_slope_lookback=3 → tail offset -4.
        ema_10_lag_3 = float(ema_series.iloc[-(ema_slope_lookback + 1)])
        ema_slope_prior = (
            ema_10_prior / ema_10_lag_3 - 1.0
            if ema_10_lag_3 != 0.0 else None
        )
    else:
        ema_10_prior = None
        ema_10_lag_3 = None
        ema_slope_prior = None

    return {
        "prior_close": prior_close,
        "prior_atr_14d": prior_atr_14d,
        "prior_atr_pct": prior_atr_pct,
        "avg_volume_20d": avg_volume_20d,
        "avg_dollar_volume_20d": avg_dollar_volume_20d,
        "ema_10_prior": ema_10_prior,
        "ema_10_lag_3": ema_10_lag_3,
        "ema_slope_prior": ema_slope_prior,
    }


def _empty_baselines() -> dict[str, float | None]:
    return {
        "prior_close": None,
        "prior_atr_14d": None,
        "prior_atr_pct": None,
        "avg_volume_20d": None,
        "avg_dollar_volume_20d": None,
        "ema_10_prior": None,
        "ema_10_lag_3": None,
        "ema_slope_prior": None,
    }


# ---------------------------------------------------------------- forming session


def aggregate_forming_session_bar(
    minute_bars_through_t: pd.DataFrame,
) -> dict[str, float | None]:
    """Aggregate minute bars up to scan time ``t`` into a forming
    session OHLCV summary. Pure: the function reads only the rows
    in the input frame.

    Caller is responsible for slicing the frame so the last row's
    timestamp is at or before the scan time. Bars beyond ``t`` must
    not be in the input — the function does NOT filter by timestamp.

    Returns ``{session_open, session_high, session_low, last_price,
    session_volume, session_range, last_bar_timestamp}``. All None
    when the frame is empty.
    """
    if minute_bars_through_t is None or len(minute_bars_through_t) == 0:
        return {
            "session_open": None, "session_high": None,
            "session_low": None, "last_price": None,
            "session_volume": None, "session_range": None,
            "last_bar_timestamp": None,
        }
    df = minute_bars_through_t
    cols = {c.lower(): c for c in df.columns}
    open_col   = cols.get("open")
    high_col   = cols.get("high")
    low_col    = cols.get("low")
    close_col  = cols.get("close")
    vol_col    = cols.get("volume")
    ts_col     = cols.get("timestamp") or cols.get("ts")

    session_open  = float(df[open_col].iloc[0]) if open_col else None
    session_high  = float(df[high_col].max())   if high_col else None
    session_low   = float(df[low_col].min())    if low_col else None
    last_price    = float(df[close_col].iloc[-1]) if close_col else None
    session_vol   = float(df[vol_col].sum())   if vol_col else None
    session_range = (
        session_high - session_low
        if (session_high is not None and session_low is not None)
        else None
    )
    last_ts = df[ts_col].iloc[-1] if ts_col else None
    if last_ts is not None:
        # Normalize to ISO 8601 string.
        if isinstance(last_ts, (pd.Timestamp, datetime)):
            ts_obj = pd.Timestamp(last_ts)
            if ts_obj.tzinfo is None:
                ts_obj = ts_obj.tz_localize("UTC")
            last_ts = ts_obj.isoformat()
        else:
            last_ts = str(last_ts)
    return {
        "session_open": session_open,
        "session_high": session_high,
        "session_low": session_low,
        "last_price": last_price,
        "session_volume": session_vol,
        "session_range": session_range,
        "last_bar_timestamp": last_ts,
    }


# ---------------------------------------------------------------- volume curve


def compute_volume_curve_fraction(
    volume_curve_df: pd.DataFrame | None,
    t: datetime | str,
    adv_bucket: str,
    *,
    fallback_opening_15m_share: float = 0.08,
) -> float:
    """Return the expected cumulative full-day volume fraction
    observed through scan time ``t`` for the given ``adv_bucket``.

    The curve frame MUST be built from prior sessions only. The
    function does not enforce that (the caller is responsible) but
    documents the contract: passing a curve that includes today's
    data is a lookahead bug.

    ``volume_curve_df`` schema:
      - ``minute_of_day`` (int, 0-389 for regular hours), OR
      - ``time`` (HH:MM string), OR
      - ``timestamp`` (datetime — interpreted as ET time-of-day)
      - ``adv_bucket`` (str)
      - ``cumulative_fraction`` (float)

    When the curve is missing or the bucket is absent, falls back
    to a flat-rate estimate (``minutes_elapsed / 390``) clamped at
    ``fallback_opening_15m_share`` for the first 15 minutes — this
    keeps the projected RVOL math sane even before the operator has
    built a proper curve.
    """
    t_et_minute = _et_minute_of_day(t)

    if volume_curve_df is None or len(volume_curve_df) == 0:
        return _fallback_curve_fraction(
            t_et_minute, fallback_opening_15m_share,
        )

    df = volume_curve_df
    cols = {c.lower(): c for c in df.columns}
    bucket_col = cols.get("adv_bucket")
    frac_col = cols.get("cumulative_fraction") or cols.get("fraction")
    min_col = cols.get("minute_of_day")

    if bucket_col is None or frac_col is None or min_col is None:
        return _fallback_curve_fraction(
            t_et_minute, fallback_opening_15m_share,
        )

    sub = df[df[bucket_col] == adv_bucket]
    if len(sub) == 0:
        return _fallback_curve_fraction(
            t_et_minute, fallback_opening_15m_share,
        )
    sub = sub.sort_values(min_col)
    # Linear-interpolate at the requested minute. Clamp to [0, 1].
    minutes = sub[min_col].to_numpy(dtype=float)
    fractions = sub[frac_col].to_numpy(dtype=float)
    if t_et_minute <= minutes[0]:
        return float(max(min(fractions[0], 1.0), 0.0))
    if t_et_minute >= minutes[-1]:
        return float(max(min(fractions[-1], 1.0), 0.0))
    interp = float(np.interp(t_et_minute, minutes, fractions))
    return max(min(interp, 1.0), 0.0)


def _et_minute_of_day(t: datetime | str) -> int:
    """Convert a scan-time argument to ET minute-of-day [0..389]
    (390 minutes in regular session, 09:30 ET = 0)."""
    if isinstance(t, str):
        ts = pd.Timestamp(t)
    else:
        ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    et = ts.tz_convert("America/New_York")
    minute = (et.hour - 9) * 60 + (et.minute - 30)
    return max(0, min(minute, 389))


def _fallback_curve_fraction(
    minute_of_day: int, fallback_opening_15m_share: float,
) -> float:
    """Linear catch-up: opening 15 minutes carry
    ``fallback_opening_15m_share`` of full-day volume, remainder
    distributed evenly across the rest of the 390-minute session."""
    if minute_of_day <= 0:
        return 0.0
    if minute_of_day <= 15:
        return fallback_opening_15m_share * (minute_of_day / 15.0)
    remainder_minutes = 390 - 15
    remainder_share = max(0.0, 1.0 - fallback_opening_15m_share)
    extra = remainder_share * ((minute_of_day - 15) / remainder_minutes)
    return min(fallback_opening_15m_share + extra, 1.0)


# ---------------------------------------------------------------- forming features


def compute_forming_session_features(
    session_bar: dict[str, float | None],
    prior_baselines: dict[str, float | None],
    volume_curve_fraction: float,
) -> dict[str, float | None]:
    """Combine the forming session bar, the prior baselines, and the
    volume-curve fraction into the v2 feature vector. Pure.

    Returns: rvol_so_far, projected_full_day_rvol,
    range_expansion_so_far, close_location_so_far, ema_distance,
    current_return_pct, gap_pct, expected_volume_until_scan.

    Any feature whose inputs are unavailable returns ``None``; the
    gate evaluator treats None as failure (fail-closed).
    """
    sess_open  = session_bar.get("session_open")
    sess_high  = session_bar.get("session_high")
    sess_low   = session_bar.get("session_low")
    last_price = session_bar.get("last_price")
    sess_vol   = session_bar.get("session_volume")
    sess_range = session_bar.get("session_range")

    prior_close   = prior_baselines.get("prior_close")
    prior_atr_14d = prior_baselines.get("prior_atr_14d")
    avg_volume_20d = prior_baselines.get("avg_volume_20d")
    ema_10_prior  = prior_baselines.get("ema_10_prior")

    # RVOL.
    if avg_volume_20d and avg_volume_20d > 0 and volume_curve_fraction > 0:
        expected_volume_until_scan = avg_volume_20d * volume_curve_fraction
    else:
        expected_volume_until_scan = None
    if expected_volume_until_scan and sess_vol is not None:
        rvol_so_far = sess_vol / expected_volume_until_scan
    else:
        rvol_so_far = None
    if avg_volume_20d and avg_volume_20d > 0 and volume_curve_fraction > 0 and sess_vol is not None:
        projected_full_day_rvol = (
            (sess_vol / volume_curve_fraction) / avg_volume_20d
        )
    else:
        projected_full_day_rvol = None

    # Range / close location.
    if prior_atr_14d and prior_atr_14d > 0 and sess_range is not None:
        range_expansion_so_far = sess_range / prior_atr_14d
    else:
        range_expansion_so_far = None
    if (sess_high is not None and sess_low is not None
            and last_price is not None and (sess_high - sess_low) > 0):
        close_location_so_far = (last_price - sess_low) / (sess_high - sess_low)
    else:
        close_location_so_far = None

    # EMA / gap / return.
    if ema_10_prior and ema_10_prior > 0 and last_price is not None:
        ema_distance = last_price / ema_10_prior - 1.0
    else:
        ema_distance = None
    if prior_close and prior_close > 0 and last_price is not None:
        current_return_pct = last_price / prior_close - 1.0
    else:
        current_return_pct = None
    if prior_close and prior_close > 0 and sess_open is not None:
        gap_pct = sess_open / prior_close - 1.0
    else:
        gap_pct = None

    return {
        "rvol_so_far": rvol_so_far,
        "projected_full_day_rvol": projected_full_day_rvol,
        "range_expansion_so_far": range_expansion_so_far,
        "close_location_so_far": close_location_so_far,
        "ema_distance": ema_distance,
        "current_return_pct": current_return_pct,
        "gap_pct": gap_pct,
        "expected_volume_until_scan": expected_volume_until_scan,
    }


# ---------------------------------------------------------------- gates


def apply_v2_gates(
    features: dict[str, float | None],
    signals_cfg: dict,
    *,
    price: float | None = None,
    avg_dollar_volume_20d: float | None = None,
    prior_atr_pct: float | None = None,
    ema_slope_prior: float | None = None,
    instrument_class: str | None = None,
) -> tuple[bool, dict[str, bool]]:
    """Apply every v2 entry gate and return ``(all_passed,
    per_gate_results)``.

    Per-gate keys (handoff §5.4 ``gate_results``): price_gate,
    avg_dollar_volume_gate, rvol_gate, projected_rvol_gate,
    prior_atr_pct_gate, range_expansion_gate, close_location_gate,
    ema_distance_gate, ema_slope_gate, max_gap_gate, max_rvol_gate,
    max_range_expansion_gate, instrument_gate.

    A gate evaluates True when its value satisfies the min/max
    constraint. Null thresholds disable the gate (always pass).
    Missing values fail closed.
    """
    s = signals_cfg or {}
    gates: dict[str, bool] = {}

    # price gate — from universe layer; passed through as a feature.
    price_min = _to_float(s.get("price_min"))
    price_max = _to_float(s.get("price_max"))
    gates["price_gate"] = _between(price, price_min, price_max)

    # avg_dollar_volume.
    adv_min = _to_float(s.get("avg_dollar_volume_min"))
    adv_max = _to_float(s.get("avg_dollar_volume_max"))
    gates["avg_dollar_volume_gate"] = _between(
        avg_dollar_volume_20d, adv_min, adv_max,
    )

    # rvol_so_far / projected.
    gates["rvol_gate"] = _ge(
        features.get("rvol_so_far"), _to_float(s.get("rvol_so_far_min")),
    )
    gates["projected_rvol_gate"] = _ge(
        features.get("projected_full_day_rvol"),
        _to_float(s.get("projected_full_day_rvol_min")),
    )

    # prior atr pct.
    gates["prior_atr_pct_gate"] = _ge(
        prior_atr_pct, _to_float(s.get("prior_atr_pct_min")),
    )

    # range expansion.
    gates["range_expansion_gate"] = _ge(
        features.get("range_expansion_so_far"),
        _to_float(s.get("range_expansion_so_far_min")),
    )

    # close location.
    gates["close_location_gate"] = _ge(
        features.get("close_location_so_far"),
        _to_float(s.get("close_location_so_far_min")),
    )

    # ema gates.
    gates["ema_distance_gate"] = _ge(
        features.get("ema_distance"), _to_float(s.get("ema_distance_min")),
    )
    gates["ema_slope_gate"] = _ge(
        ema_slope_prior, _to_float(s.get("ema_slope_min")),
    )

    # Max gates (blow-off / exhaustion guards).
    gates["max_gap_gate"] = _le(
        features.get("gap_pct"), _to_float(s.get("gap_pct_max")),
    )
    gates["max_rvol_gate"] = _le(
        features.get("rvol_so_far"), _to_float(s.get("rvol_so_far_max")),
    )
    gates["max_range_expansion_gate"] = _le(
        features.get("range_expansion_so_far"),
        _to_float(s.get("range_expansion_so_far_max")),
    )

    # Instrument class.
    gates["instrument_gate"] = (
        instrument_class is None
        or instrument_class == "operating_equity"
    )

    all_passed = all(gates.values())
    return all_passed, gates


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ge(val: float | None, threshold: float | None) -> bool:
    """value >= threshold. Null threshold = disabled (pass). Null
    value = fail closed."""
    if threshold is None:
        return True
    if val is None:
        return False
    return float(val) >= float(threshold)


def _le(val: float | None, threshold: float | None) -> bool:
    """value <= threshold. Null threshold = disabled (pass). Null
    value = pass (max-cap can't fail on missing data)."""
    if threshold is None:
        return True
    if val is None:
        return True
    return float(val) <= float(threshold)


def _between(
    val: float | None, lo: float | None, hi: float | None,
) -> bool:
    """value within [lo, hi]. Either bound null disables that side.
    Null value fails closed."""
    if val is None and (lo is not None or hi is not None):
        return False
    if val is None:
        return True
    if lo is not None and float(val) < float(lo):
        return False
    if hi is not None and float(val) > float(hi):
        return False
    return True


# ---------------------------------------------------------------- score


def compute_signal_strength(
    features: dict[str, float | None],
    score_cfg: dict,
    *,
    ema_slope_prior: float | None = None,
) -> float:
    """Compute the v2 candidate signal_strength.

    ``bounded: true`` (default in v2 per handoff §4.5) uses the
    bounded formula:

        score = 1.00 * min(rvol_so_far, rvol_score_cap)
              + 1.00 * min(range_expansion_so_far, range_score_cap)
              + 0.75 * close_location_so_far     (or close_location_weight)
              + 10.0 * clip(ema_distance, 0, ema_distance_score_cap)
              + 10.0 * clip(ema_slope_prior, 0, ema_slope_score_cap)
              - 1.00 * max(gap_pct - gap_penalty_above, 0)

    ``bounded: false`` reproduces the v1 unbounded form: pure
    weighted sum with no clips, used only for legacy parity tests.
    """
    cfg = score_cfg or {}
    bounded = bool(cfg.get("bounded", True))

    rvol  = _to_float(features.get("rvol_so_far")) or 0.0
    rng   = _to_float(features.get("range_expansion_so_far")) or 0.0
    cl    = _to_float(features.get("close_location_so_far")) or 0.0
    ed    = _to_float(features.get("ema_distance")) or 0.0
    es    = _to_float(ema_slope_prior) or 0.0
    gap   = _to_float(features.get("gap_pct")) or 0.0

    cl_weight = float(cfg.get("close_location_weight", 0.75))
    gap_above = float(cfg.get("gap_penalty_above", 0.25))

    if bounded:
        rvol_cap   = float(cfg.get("rvol_score_cap", 5.0))
        rng_cap    = float(cfg.get("range_score_cap", 2.5))
        ed_cap     = float(cfg.get("ema_distance_score_cap", 0.40))
        es_cap     = float(cfg.get("ema_slope_score_cap", 0.25))
        rvol_term  = min(max(rvol, 0.0), rvol_cap)
        rng_term   = min(max(rng, 0.0), rng_cap)
        ed_term    = min(max(ed, 0.0), ed_cap)
        es_term    = min(max(es, 0.0), es_cap)
        score = (
            1.00 * rvol_term
            + 1.00 * rng_term
            + cl_weight * cl
            + 10.0 * ed_term
            + 10.0 * es_term
            - 1.00 * max(gap - gap_above, 0.0)
        )
    else:
        # Legacy unbounded form — pure weighted sum, no clips.
        score = (
            1.00 * rvol
            + 1.00 * rng
            + cl_weight * cl
            + 10.0 * ed
            + 10.0 * es
            - 1.00 * max(gap - gap_above, 0.0)
        )
    return float(score)


__all__ = [
    "compute_prior_daily_baselines",
    "aggregate_forming_session_bar",
    "compute_volume_curve_fraction",
    "compute_forming_session_features",
    "apply_v2_gates",
    "compute_signal_strength",
]
