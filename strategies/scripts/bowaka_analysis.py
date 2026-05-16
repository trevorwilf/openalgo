"""Bowaka trade-log analysis toolkit.

Loads the per-trade JSONL files at ``data/trades/<link_id>.jsonl``
plus the cross-trade roll-up at ``data/daily_summary.jsonl`` into
pandas DataFrames and computes the cohort comparisons a quant uses to
tune target_pct / stop_pct / max_hold_days / signal_gates / sizing.

Two ways to use it:

1. As a script: ``python bowaka_analysis.py`` prints the headline
   tables (slot-index alpha, gate marginal-pass, exit-reason
   breakdown, MFE/MAE percentiles, slippage summary, drawdown-before-
   stop). One-shot tuning report.

2. As a module from a Jupyter notebook:
       from bowaka_analysis import load_records, to_closed_trades, ...
       df = load_records(Path('data/trades'))
       closed = to_closed_trades(df)

The script is read-only; nothing here ever writes to the trade logs.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


# ----------------------------------------------------------------- loading


def load_records(trades_dir: Path) -> pd.DataFrame:
    """Walk every ``*.jsonl`` under ``trades_dir`` and return one long
    DataFrame of records. ``ts`` is parsed to UTC timestamps; nested
    dicts are kept as cell values for downstream flattening.

    Adds two helper columns:
      * ``_source_file`` — the file the record came from.
      * ``_record_idx`` — 0-based line number within its file (lets
        you reconstruct the chronological order of a single trade).
    """
    if not trades_dir.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for path in sorted(trades_dir.glob("*.jsonl")):
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec["_source_file"] = path.name
            rec["_record_idx"] = idx
            rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    return df


def load_daily_summary(summary_path: Path) -> pd.DataFrame:
    """Same shape contract as ``load_records`` but for the cross-
    trade roll-up file. Useful when you want closures from positions
    whose per-trade file was deleted (or never written, e.g. legacy
    pre-rich-logging entries)."""
    if not summary_path.exists():
        return pd.DataFrame()
    rows = []
    for line in summary_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(rec)
    df = pd.DataFrame(rows)
    for col in ("ts", "entry_timestamp", "exit_timestamp"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


# ----------------------------------------------------------------- Phase 7 — ledger-based analysis


def load_ledger(ledger_path: Path) -> pd.DataFrame:
    """Phase 7.4: read the canonical trade ledger as a flat DataFrame.

    Each row is one ledger event. Returns an empty DataFrame when
    ``ledger_path`` does not exist (legacy installs without a
    ledger). The ``ts`` and ``session_date`` columns are parsed to
    datetimes; ``payload`` stays as a dict for downstream
    flattening.
    """
    if not ledger_path.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(ev)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    return df


def _payload_get(p: Any, *path, default=None):
    """Safely walk a nested payload dict, returning ``default`` on
    any KeyError / TypeError. Same helper as ``_g`` in to_decisions
    but local so the function is self-contained for reuse."""
    cur = p
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def build_canonical_trade_table(ledger_path: Path) -> pd.DataFrame:
    """Phase 7.4: project the ledger into one row per trade_id.

    Columns:
      trade_id, ticker, session_date, entry_trigger,
      entry_timestamp, exit_timestamp, entry_price, exit_price,
      qty, planned_risk_dollars, realized_pnl, R_multiple,
      reason (exit), instrument_class, entry_features (dict),
      mfe_pct, mae_pct, hold_trading_days, candidate_rank,
      spread_pct_at_decision, avg_dollar_volume, venue_code,
      exchange, entry_order_style, entry_limit_price.

    Rows without a closure event have NaN exit fields. Correction
    events override the original closure (last-write-wins by ts).
    """
    df = load_ledger(ledger_path)
    if df.empty:
        return pd.DataFrame()

    by_trade: dict[str, dict[str, Any]] = {}

    # First pass: entry_decisions (accepted) + order_fills (parent)
    # populate the entry side of each trade.
    for _, row in df.iterrows():
        et = row.get("event_type")
        trade_id = row.get("trade_id") or ""
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if et == "entry_decision":
            if payload.get("decision") != "accepted" or not trade_id:
                continue
            r = by_trade.setdefault(trade_id, {})
            r["trade_id"] = trade_id
            r["ticker"] = payload.get("ticker") or row.get("ticker")
            r["session_date"] = row.get("session_date")
            r["entry_trigger"] = payload.get("entry_trigger")
            r["candidate_rank"] = payload.get("candidate_rank")
            r["entry_features"] = _payload_get(payload, "candidate", "features")
            r["avg_dollar_volume"] = _payload_get(
                payload, "sizing", "avg_dollar_volume",
            )
            quote = payload.get("quote")
            r["spread_pct_at_decision"] = (
                ((quote.get("ask") or 0) - (quote.get("bid") or 0))
                / (((quote.get("ask") or 0) + (quote.get("bid") or 0)) / 2.0)
                if isinstance(quote, dict) and (quote.get("ask") or 0) > 0
                and (quote.get("bid") or 0) > 0
                else None
            )
            r["venue_code"] = payload.get("venue_code")
            r["exchange"] = payload.get("exchange")
            r["instrument_class"] = _payload_get(
                payload, "candidate", "features", "instrument_class",
            )

        elif et == "order_fill" and row.get("role") == "parent":
            r = by_trade.setdefault(trade_id, {})
            r["entry_price"] = payload.get("filled_avg_price")
            r["qty"] = payload.get("filled_qty")
            r["entry_timestamp"] = row.get("ts")
        elif et == "closure":
            r = by_trade.setdefault(trade_id, {})
            r["exit_price"] = payload.get("exit_price")
            r["exit_timestamp"] = (
                payload.get("exit_timestamp") or row.get("ts")
            )
            r["realized_pnl"] = payload.get("realized_pnl")
            r["reason"] = payload.get("reason")
            r["mfe_pct"] = payload.get("mfe_pct")
            r["mae_pct"] = payload.get("mae_pct")
            r["hold_trading_days"] = payload.get("hold_trading_days")
            r["planned_risk_dollars"] = payload.get("planned_risk_dollars")
            r["R_multiple"] = payload.get("R_multiple")
            r["entry_order_style"] = payload.get("entry_order_style")
            r["entry_limit_price"] = payload.get("entry_limit_price")
            if not r.get("session_date"):
                r["session_date"] = row.get("session_date")
        elif et == "correction":
            # Last-write-wins overlay of the closure payload.
            r = by_trade.setdefault(trade_id, {})
            for k in ("exit_price", "realized_pnl", "reason",
                      "mfe_pct", "mae_pct", "hold_trading_days",
                      "planned_risk_dollars", "R_multiple"):
                if k in payload:
                    r[k] = payload[k]

    if not by_trade:
        return pd.DataFrame()
    out = pd.DataFrame(list(by_trade.values()))
    return out


# ---------------------------------------------------------------- Phase 7.4 reports


def _bucketize(series: pd.Series, edges: list[float],
               labels: list[str] | None = None) -> pd.Series:
    return pd.cut(series, bins=edges, labels=labels, include_lowest=True)


def report_by_entry_trigger(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "entry_trigger" not in trades.columns:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    grouped = closed.groupby("entry_trigger", dropna=False).agg(
        trades=("realized_pnl", "size"),
        total_pnl=("realized_pnl", "sum"),
        mean_pnl=("realized_pnl", "mean"),
        win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
    ).reset_index()
    return grouped


def report_by_instrument_class(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "instrument_class" not in trades.columns:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    return closed.groupby("instrument_class", dropna=False).agg(
        trades=("realized_pnl", "size"),
        total_pnl=("realized_pnl", "sum"),
        mean_pnl=("realized_pnl", "mean"),
        win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
    ).reset_index()


def report_by_adv_tier(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "avg_dollar_volume" not in trades.columns:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    edges = [0, 500_000, 1_000_000, 5_000_000, 50_000_000, float("inf")]
    labels = ["<500k", "500k-1M", "1M-5M", "5M-50M", ">50M"]
    closed["adv_tier"] = _bucketize(
        closed["avg_dollar_volume"].astype(float), edges, labels,
    )
    return closed.groupby("adv_tier", observed=False).agg(
        trades=("realized_pnl", "size"),
        total_pnl=("realized_pnl", "sum"),
        mean_pnl=("realized_pnl", "mean"),
        win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
    ).reset_index()


def report_by_spread_bucket(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "spread_pct_at_decision" not in trades.columns:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    edges = [0, 0.005, 0.01, 0.02, 0.05, float("inf")]
    labels = ["<0.5%", "0.5-1%", "1-2%", "2-5%", ">5%"]
    closed["spread_bucket"] = _bucketize(
        closed["spread_pct_at_decision"].astype(float), edges, labels,
    )
    return closed.groupby("spread_bucket", observed=False).agg(
        trades=("realized_pnl", "size"),
        total_pnl=("realized_pnl", "sum"),
        mean_pnl=("realized_pnl", "mean"),
        win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
    ).reset_index()


def report_mfe_mae_distribution(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    rows = []
    for col in ("mfe_pct", "mae_pct"):
        if col in closed.columns:
            s = closed[col].dropna().astype(float)
            if not s.empty:
                rows.append({
                    "metric": col,
                    "min": s.min(), "p10": s.quantile(0.1),
                    "p50": s.median(), "p90": s.quantile(0.9),
                    "max": s.max(), "mean": s.mean(),
                })
    return pd.DataFrame(rows)


def report_stop_slippage(trades: pd.DataFrame) -> pd.DataFrame:
    """Stop slippage = planned stop vs actual exit_price on stop_hit."""
    if trades.empty:
        return pd.DataFrame()
    closed = trades[trades.get("reason") == "stop_hit"].copy()
    if closed.empty:
        return pd.DataFrame()
    # Planned stop = entry_price * (1 - stop_pct) — we don't have
    # stop_pct directly in the trade row; approximate via
    # planned_risk_dollars / (entry_price * qty) when available.
    closed["slippage_dollars"] = closed.apply(
        lambda r: float(r.get("realized_pnl") or 0)
        + float(r.get("planned_risk_dollars") or 0),
        axis=1,
    )
    s = closed["slippage_dollars"]
    return pd.DataFrame([{
        "stop_hit_trades": len(closed),
        "median_slippage_dollars": s.median(),
        "mean_slippage_dollars": s.mean(),
        "worst_slippage_dollars": s.min(),
    }])


def report_ex_top_winners(trades: pd.DataFrame) -> pd.DataFrame:
    """PnL excluding top 1 / top 5 winners — sanity check for skew."""
    if trades.empty:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    if closed.empty:
        return pd.DataFrame()
    sorted_pnl = closed["realized_pnl"].astype(float).sort_values(ascending=False)
    rows = [
        {"basis": "all", "n": int(len(sorted_pnl)),
         "total_pnl": float(sorted_pnl.sum())},
        {"basis": "ex_top_1", "n": int(len(sorted_pnl) - 1),
         "total_pnl": float(sorted_pnl.iloc[1:].sum())},
        {"basis": "ex_top_5", "n": int(max(len(sorted_pnl) - 5, 0)),
         "total_pnl": float(sorted_pnl.iloc[5:].sum())},
    ]
    return pd.DataFrame(rows)


def report_rescreen_ablation(trades: pd.DataFrame) -> pd.DataFrame:
    """PnL with rescreen entries included vs excluded."""
    if trades.empty or "entry_trigger" not in trades.columns:
        return pd.DataFrame()
    closed = trades.dropna(subset=["realized_pnl"]).copy()
    rescreen_trades = closed[closed["entry_trigger"] == "post_closure_rescreen"]
    open_trades = closed[closed["entry_trigger"] != "post_closure_rescreen"]
    return pd.DataFrame([
        {"basis": "all", "n": int(len(closed)),
         "total_pnl": float(closed["realized_pnl"].sum())},
        {"basis": "ex_rescreen", "n": int(len(open_trades)),
         "total_pnl": float(open_trades["realized_pnl"].sum())},
        {"basis": "rescreen_only", "n": int(len(rescreen_trades)),
         "total_pnl": float(rescreen_trades["realized_pnl"].sum())},
    ])


# ---------------------------------------------------------------- Phase 7.5 reconcile guard


def reconcile_ledger_vs_summary(
    ledger_path: Path, summary_path: Path,
    *,
    include_test_fixtures: bool = False,
) -> dict[str, Any]:
    """Phase 7.5: rebuild a daily_summary projection from the ledger
    for every date it covers, compare against the on-disk session_
    summary records, and report differences.

    Returns a dict with ``differences`` (list of {date, field, on_disk,
    expected}) and ``matched`` (count). Operators run this in CI to
    catch ledger / summary drift.

    The ``include_test_fixtures`` flag is threaded through to
    :func:`recompute_daily_summary_from_ledger` — without it the
    ledger reader refuses to project a mixed-environment ledger
    (Phase 1.5 guardrail).
    """
    # Import here to avoid circular dep when this module is imported
    # before bowaka_strategy in test harnesses.
    import bowaka_strategy as bw

    ledger_df = load_ledger(ledger_path)
    summary_df = load_daily_summary(summary_path)
    if ledger_df.empty:
        return {"differences": [], "matched": 0,
                "note": "empty ledger — nothing to compare"}

    on_disk_summaries: dict[str, dict[str, Any]] = {}
    if not summary_df.empty and "record_type" in summary_df.columns:
        for _, row in summary_df.iterrows():
            if row.get("record_type") != "session_summary":
                continue
            date_str = row.get("session_date")
            # Last write wins (matches reconcile_summary_for_date
            # appending corrections).
            if date_str:
                on_disk_summaries[date_str] = row.to_dict()

    differences: list[dict[str, Any]] = []
    matched = 0
    dates_in_ledger = sorted(
        d for d in ledger_df["session_date"].dropna().unique()
    )
    for date_str in dates_in_ledger:
        expected = bw.recompute_daily_summary_from_ledger(
            ledger_path, date_str,
            include_test_fixtures=include_test_fixtures,
        )
        on_disk = on_disk_summaries.get(date_str)
        if on_disk is None:
            differences.append({
                "date": date_str, "field": "*", "on_disk": None,
                "expected": expected,
            })
            continue
        for k in ("count_opened", "count_closed", "total_realized_pnl"):
            d = on_disk.get(k)
            e = expected.get(k)
            if d != e:
                differences.append({
                    "date": date_str, "field": k,
                    "on_disk": d, "expected": e,
                })
        if not any(d["date"] == date_str for d in differences):
            matched += 1
    return {"differences": differences, "matched": matched}


# ----------------------------------------------------------------- shape transforms


_GATE_KEYS = (
    "rvol", "atr_pct", "range_expansion",
    "close_location", "ema_distance", "ema_slope",
)


def to_decisions(records: pd.DataFrame) -> pd.DataFrame:
    """One row per ``entry_decision`` record. Flattens the nested
    ``candidate``, ``gates``, ``selection``, ``sizing``, ``bracket``,
    ``risk`` blocks into columns. Returns empty DF when no decisions
    have been recorded yet."""
    if records.empty or "record_type" not in records.columns:
        return pd.DataFrame()
    sub = records[records.record_type == "entry_decision"].copy()
    if sub.empty:
        return sub.reset_index(drop=True)

    def _g(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
        return cur if cur is not None else default

    out = pd.DataFrame({
        "ts": sub["ts"],
        "ticker": sub["ticker"],
        "link_id": sub["link_id"],
        "venue_code": sub.get("venue_code"),
        "exchange": sub.get("exchange"),
        "candidate_close": [_g(c, "close") for c in sub.get("candidate", [{}] * len(sub))],
        "signal_strength": [_g(c, "signal_strength") for c in sub.get("candidate", [{}] * len(sub))],
        "slot_index": [_g(s, "slot_index") for s in sub.get("selection", [{}] * len(sub))],
        "slate_size": [_g(s, "slate_size") for s in sub.get("selection", [{}] * len(sub))],
        "qty": [_g(s, "qty") for s in sub.get("sizing", [{}] * len(sub))],
        "notional_at_close": [_g(s, "notional_at_close") for s in sub.get("sizing", [{}] * len(sub))],
        "equity_at_entry": [_g(s, "equity_at_entry") for s in sub.get("sizing", [{}] * len(sub))],
        "binding_cap": [_g(s, "binding_cap") for s in sub.get("sizing", [{}] * len(sub))],
        "adv_cap_dollars": [_g(s, "adv_cap_dollars") for s in sub.get("sizing", [{}] * len(sub))],
        "target_dollars": [_g(s, "target_dollars") for s in sub.get("sizing", [{}] * len(sub))],
        "bracket_mode": [_g(b, "mode") for b in sub.get("bracket", [{}] * len(sub))],
        "target_pct": [_g(b, "target_pct") for b in sub.get("bracket", [{}] * len(sub))],
        "stop_pct": [_g(b, "stop_pct") for b in sub.get("bracket", [{}] * len(sub))],
        "max_hold_days": [_g(b, "max_hold_days") for b in sub.get("bracket", [{}] * len(sub))],
    })
    # Per-feature columns from the candidate features dict.
    for k in _GATE_KEYS + ("avg_dollar_volume", "gap_pct"):
        out[f"feat_{k}"] = [
            _g(c, "features", k) for c in sub.get("candidate", [{}] * len(sub))
        ]
    # Per-gate margin (value / threshold). Captures HOW comfortably
    # each gate passed at entry — bucket into "just above" vs
    # "far above" to study which range generates the most edge.
    for k in _GATE_KEYS:
        vals = [_g(g, k, "value") for g in sub.get("gates", [{}] * len(sub))]
        thrs = [_g(g, k, "threshold") for g in sub.get("gates", [{}] * len(sub))]
        out[f"gate_{k}_value"] = vals
        out[f"gate_{k}_threshold"] = thrs
        out[f"gate_{k}_margin"] = [
            (v / t) if (v is not None and t not in (None, 0)) else None
            for v, t in zip(vals, thrs)
        ]
    return out.reset_index(drop=True)


def to_exits(records: pd.DataFrame) -> pd.DataFrame:
    """One row per ``exit`` record (per-trade jsonl). Falls back to
    closures from the daily_summary roll-up if records is empty."""
    if records.empty or "record_type" not in records.columns:
        return pd.DataFrame()
    sub = records[records.record_type == "exit"].copy()
    if sub.empty:
        return sub.reset_index(drop=True)
    keep_cols = [
        "ts", "ticker", "link_id",
        "entry_price", "exit_price", "qty", "realized_pnl", "reason",
        "hold_trading_days", "entry_to_exit_pct",
        "mfe_dollar", "mae_dollar", "mfe_pct", "mae_pct",
        "peak_since_entry", "trough_since_entry",
        "venue_code", "exchange",
        "signal_strength", "candidate_close",
        "target_pct", "stop_pct", "bracket_pricing_mode",
    ]
    return sub.reindex(columns=[c for c in keep_cols if c in sub.columns]).reset_index(drop=True)


def to_closed_trades(records: pd.DataFrame) -> pd.DataFrame:
    """Joined view: each closed trade as one row with both entry-
    decision context and exit metrics. The link_id is the join key.

    Columns shared between the entry and exit sides are trade-
    identity fields (ticker, venue_code, exchange) or config
    snapshots (target_pct, stop_pct, candidate_close, etc.) — they
    have the same value on both sides because they were stamped
    when the trade was opened and don't change. Drop them from the
    decisions side before merging so the result has clean,
    unsuffixed column names.
    """
    decisions = to_decisions(records)
    exits = to_exits(records)
    if decisions.empty or exits.empty:
        return pd.DataFrame()
    overlap = {
        "ts", "ticker", "venue_code", "exchange",
        "signal_strength", "candidate_close",
        "target_pct", "stop_pct",
    }
    decisions_for_merge = decisions.drop(
        columns=[c for c in overlap if c in decisions.columns],
    )
    df = exits.merge(decisions_for_merge, on="link_id", how="inner")
    return df


def to_ticks(records: pd.DataFrame) -> pd.DataFrame:
    """Long-form intraday ticks. One row per (link_id, ts).
    Quote/position/excursion/distance/time blocks flattened into
    columns named after their JSON path."""
    if records.empty or "record_type" not in records.columns:
        return pd.DataFrame()
    sub = records[records.record_type == "intraday_tick"].copy()
    if sub.empty:
        return sub.reset_index(drop=True)

    def _g(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
        return cur if cur is not None else default

    flat = pd.DataFrame({
        "ts": sub["ts"], "link_id": sub["link_id"], "ticker": sub["ticker"],
        "bid": [_g(q, "bid") for q in sub.get("quote", [{}] * len(sub))],
        "ask": [_g(q, "ask") for q in sub.get("quote", [{}] * len(sub))],
        "mid": [_g(q, "mid") for q in sub.get("quote", [{}] * len(sub))],
        "spread": [_g(q, "spread") for q in sub.get("quote", [{}] * len(sub))],
        "spread_pct": [_g(q, "spread_pct") for q in sub.get("quote", [{}] * len(sub))],
        "last": [_g(q, "last") for q in sub.get("quote", [{}] * len(sub))],
        "session_volume": [_g(b, "volume") for b in sub.get("session_bar", [{}] * len(sub))],
        "session_high": [_g(b, "high") for b in sub.get("session_bar", [{}] * len(sub))],
        "session_low": [_g(b, "low") for b in sub.get("session_bar", [{}] * len(sub))],
        "gap_from_prev_close_pct": [
            _g(b, "gap_from_prev_close_pct") for b in sub.get("session_bar", [{}] * len(sub))
        ],
        "unrealized_pnl": [_g(p, "unrealized_pnl") for p in sub.get("position", [{}] * len(sub))],
        "unrealized_pnl_pct": [_g(p, "unrealized_pnl_pct") for p in sub.get("position", [{}] * len(sub))],
        "peak_since_entry": [_g(e, "peak_since_entry") for e in sub.get("excursion", [{}] * len(sub))],
        "trough_since_entry": [_g(e, "trough_since_entry") for e in sub.get("excursion", [{}] * len(sub))],
        "mfe_dollar": [_g(e, "mfe_dollar") for e in sub.get("excursion", [{}] * len(sub))],
        "mae_dollar": [_g(e, "mae_dollar") for e in sub.get("excursion", [{}] * len(sub))],
        "drawdown_from_peak_pct": [_g(e, "drawdown_from_peak_pct") for e in sub.get("excursion", [{}] * len(sub))],
        "to_target_pct": [_g(d, "to_target_pct") for d in sub.get("distance", [{}] * len(sub))],
        "to_stop_pct": [_g(d, "to_stop_pct") for d in sub.get("distance", [{}] * len(sub))],
        "minutes_held": [_g(t, "minutes_held") for t in sub.get("time", [{}] * len(sub))],
    })
    return flat.sort_values(["link_id", "ts"]).reset_index(drop=True)


# ----------------------------------------------------------------- analyses


def slot_alpha(closed: pd.DataFrame) -> pd.DataFrame:
    """Realized-P&L stats grouped by selection slot_index. If the top
    pick (slot 0) reliably beats slot 4, your signal_strength ranking
    is doing real work; if the buckets are flat, max_concurrent could
    drop without losing edge."""
    if closed.empty or "slot_index" not in closed.columns:
        return pd.DataFrame()
    g = closed.groupby("slot_index")["realized_pnl"]
    return pd.DataFrame({
        "n": g.count(),
        "win_rate": (closed["realized_pnl"] > 0).groupby(closed["slot_index"]).mean(),
        "mean_pnl": g.mean(),
        "median_pnl": g.median(),
        "stdev_pnl": g.std(),
        "total_pnl": g.sum(),
    }).reset_index()


def gate_marginal_pass(closed: pd.DataFrame) -> pd.DataFrame:
    """Bucket entries by per-gate margin (value / threshold) and
    compare realized P&L. A flat distribution means the gate is
    additive; a strong gradient (e.g. higher rvol → better PnL)
    means raising the gate threshold would lift expected return."""
    if closed.empty:
        return pd.DataFrame()
    rows = []
    bucket_edges = [1.0, 1.2, 1.5, 2.0, 5.0, math.inf]
    bucket_labels = ["1.0-1.2x", "1.2-1.5x", "1.5-2x", "2-5x", ">5x"]
    for k in _GATE_KEYS:
        col = f"gate_{k}_margin"
        if col not in closed.columns:
            continue
        margins = closed[col].astype(float)
        # Some gates are "value >= threshold" with threshold=0 — those
        # have margin=inf which we put in the >5x bucket.
        clean = closed.assign(_margin=margins).dropna(subset=["_margin", "realized_pnl"])
        if clean.empty:
            continue
        clean["_bucket"] = pd.cut(
            clean["_margin"], bins=bucket_edges, labels=bucket_labels,
            include_lowest=True,
        )
        for bucket, sub in clean.groupby("_bucket", observed=True):
            if sub.empty:
                continue
            rows.append({
                "gate": k,
                "margin_bucket": str(bucket),
                "n": len(sub),
                "win_rate": (sub["realized_pnl"] > 0).mean(),
                "mean_pnl": sub["realized_pnl"].mean(),
                "median_pnl": sub["realized_pnl"].median(),
            })
    return pd.DataFrame(rows)


def exit_reason_breakdown(closed: pd.DataFrame) -> pd.DataFrame:
    """Counts, win-rate, and PnL stats per exit reason. Lets you see
    which exit code is paying for the strategy and which is bleeding."""
    if closed.empty or "reason" not in closed.columns:
        return pd.DataFrame()
    g = closed.groupby("reason")["realized_pnl"]
    return pd.DataFrame({
        "n": g.count(),
        "mean_pnl": g.mean(),
        "median_pnl": g.median(),
        "total_pnl": g.sum(),
        "mean_hold_days": closed.groupby("reason")["hold_trading_days"].mean(),
    }).reset_index().sort_values("total_pnl", ascending=False)


def mfe_mae_distribution(closed: pd.DataFrame) -> pd.DataFrame:
    """Percentiles of MFE % and MAE % by exit reason. Read as:
    'for stop_hit exits, the median MFE was X% — that's the
    profit you left on the table by sitting through the drawdown.'"""
    if closed.empty or "mfe_pct" not in closed.columns:
        return pd.DataFrame()
    rows = []
    for reason, sub in closed.groupby("reason"):
        mfe = sub["mfe_pct"].dropna()
        mae = sub["mae_pct"].dropna()
        rows.append({
            "reason": reason, "n": len(sub),
            "mfe_pct_p25": mfe.quantile(0.25) if len(mfe) else None,
            "mfe_pct_p50": mfe.quantile(0.50) if len(mfe) else None,
            "mfe_pct_p75": mfe.quantile(0.75) if len(mfe) else None,
            "mae_pct_p25": mae.quantile(0.25) if len(mae) else None,
            "mae_pct_p50": mae.quantile(0.50) if len(mae) else None,
            "mae_pct_p75": mae.quantile(0.75) if len(mae) else None,
        })
    return pd.DataFrame(rows)


def slippage_summary(records: pd.DataFrame) -> pd.DataFrame:
    """Entry-side slippage analysis from ``entry_fill`` records.
    Quantifies the cost of using MARKET BUYs vs the candidate close.
    A large positive slippage means we're chasing names that
    already gapped up — a candidate selection problem (max-gap-at-
    open filter would help)."""
    if records.empty:
        return pd.DataFrame()
    sub = records[records.record_type == "entry_fill"].copy()
    if sub.empty:
        return pd.DataFrame()
    s = sub["slippage_vs_candidate_close_pct"].astype(float).dropna()
    return pd.DataFrame([{
        "n": len(s),
        "mean_slippage_pct": s.mean(),
        "median_slippage_pct": s.median(),
        "p25": s.quantile(0.25),
        "p75": s.quantile(0.75),
        "p95": s.quantile(0.95),
        "min": s.min(),
        "max": s.max(),
        "fraction_positive_slippage": (s > 0).mean(),
    }])


def drawdown_before_stop(ticks: pd.DataFrame, closed: pd.DataFrame) -> pd.DataFrame:
    """For each ``stop_hit`` closure, compute the deepest
    drawdown_from_peak_pct observed BEFORE the stop fired. If
    drawdowns cluster much shallower than the stop %, the stop is
    too tight and could be loosened; if many touched 90% of the
    stop and recovered, a tighter stop would have triggered fewer
    wins — measure both directions."""
    if ticks.empty or closed.empty:
        return pd.DataFrame()
    stops = closed[closed.reason == "stop_hit"]
    if stops.empty:
        return pd.DataFrame()
    rows = []
    for _, row in stops.iterrows():
        link = row["link_id"]
        sub = ticks[ticks.link_id == link]
        if sub.empty:
            continue
        rows.append({
            "link_id": link,
            "ticker": row["ticker"],
            "stop_pct": row.get("stop_pct"),
            "deepest_drawdown_pct": sub["drawdown_from_peak_pct"].min(),
            "max_mfe_dollar_seen": sub["mfe_dollar"].max(),
            "n_ticks": len(sub),
        })
    return pd.DataFrame(rows)


def runup_before_target(ticks: pd.DataFrame, closed: pd.DataFrame) -> pd.DataFrame:
    """For each ``target_hit`` closure, the highest drawdown the
    position survived before paying. Frequent deep drawdowns on
    eventual winners say "the stop is appropriately wide" — moving
    it tighter would kill these."""
    if ticks.empty or closed.empty:
        return pd.DataFrame()
    wins = closed[closed.reason == "target_hit"]
    if wins.empty:
        return pd.DataFrame()
    rows = []
    for _, row in wins.iterrows():
        link = row["link_id"]
        sub = ticks[ticks.link_id == link]
        if sub.empty:
            continue
        rows.append({
            "link_id": link,
            "ticker": row["ticker"],
            "stop_pct": row.get("stop_pct"),
            "deepest_drawdown_before_target": sub["drawdown_from_peak_pct"].min(),
            "max_mfe_dollar_seen": sub["mfe_dollar"].max(),
            "n_ticks": len(sub),
        })
    return pd.DataFrame(rows)


def hold_duration_profile(closed: pd.DataFrame) -> pd.DataFrame:
    """Hold-trading-days × exit-reason distribution. Lets you see
    whether stop_hit exits cluster early (intraday volatility
    rejection) or late (signal decayed); same for target_hit
    (immediate breakout vs slow grind)."""
    if closed.empty or "hold_trading_days" not in closed.columns:
        return pd.DataFrame()
    g = closed.groupby(["reason", "hold_trading_days"]).size().reset_index(name="n")
    pivot = g.pivot(index="hold_trading_days", columns="reason", values="n").fillna(0)
    return pivot.astype(int).reset_index()


def gap_at_open_vs_outcome(records: pd.DataFrame, closed: pd.DataFrame) -> pd.DataFrame:
    """Bucket trades by gap_at_open_pct (entry_fill_price vs
    candidate_close); compare realized PnL. Heavy losses in big-gap
    cohorts → add a max_gap_at_open rejection rule to the entry
    pass; flat distribution → gap is uninformative for THIS strategy
    and the rule isn't needed."""
    if records.empty or closed.empty:
        return pd.DataFrame()
    fills = records[records.record_type == "entry_fill"][
        ["link_id", "slippage_vs_candidate_close_pct"]
    ].rename(columns={"slippage_vs_candidate_close_pct": "gap_at_open_pct"})
    if fills.empty:
        return pd.DataFrame()
    df = closed.merge(fills, on="link_id", how="left")
    df = df.dropna(subset=["gap_at_open_pct", "realized_pnl"])
    if df.empty:
        return pd.DataFrame()
    bins = [-1, -0.05, -0.01, 0.01, 0.05, 0.10, 0.20, 1]
    labels = ["<-5%", "-5%--1%", "-1%-+1%", "+1%-+5%", "+5%-+10%", "+10%-+20%", ">+20%"]
    df["gap_bucket"] = pd.cut(df["gap_at_open_pct"], bins=bins, labels=labels)
    g = df.groupby("gap_bucket", observed=True)["realized_pnl"]
    return pd.DataFrame({
        "n": g.count(),
        "win_rate": (df["realized_pnl"] > 0).groupby(df["gap_bucket"], observed=True).mean(),
        "mean_pnl": g.mean(),
        "median_pnl": g.median(),
        "total_pnl": g.sum(),
    }).reset_index()


# ----------------------------------------------------------------- driver


def _print_section(title: str, df: pd.DataFrame) -> None:
    print()
    print("=" * len(title))
    print(title)
    print("=" * len(title))
    if df is None or df.empty:
        print("  (no data)")
        return
    with pd.option_context(
        "display.max_columns", None,
        "display.width", 180,
        "display.float_format", "{:.4f}".format,
    ):
        print(df.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bowaka trade-log analysis")
    parser.add_argument(
        "--trades-dir",
        default=str(Path(__file__).resolve().parent / "data" / "trades"),
        help="Directory containing per-trade <link_id>.jsonl files",
    )
    parser.add_argument(
        "--summary",
        default=str(Path(__file__).resolve().parent / "data" / "daily_summary.jsonl"),
        help="Cross-trade roll-up jsonl (used as fallback for closures)",
    )
    parser.add_argument(
        "--ledger",
        default=str(Path(__file__).resolve().parent / "data" / "trade_ledger.jsonl"),
        help="Phase 7.4: canonical trade ledger (read by Phase 7 reports)",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Phase 7.5: rebuild session summary from ledger and diff "
             "against on-disk daily_summary. Exits non-zero on mismatch.",
    )
    parser.add_argument(
        "--include-test-fixtures",
        action="store_true",
        help="Phase 1.5: allow mixed-environment ledgers. Without this "
             "flag the ledger reader refuses to roll up a ledger that "
             "contains both paper and test events, so synthetic "
             "fixtures cannot silently contaminate paper analysis.",
    )
    args = parser.parse_args(argv)

    if args.reconcile:
        result = reconcile_ledger_vs_summary(
            Path(args.ledger), Path(args.summary),
            include_test_fixtures=args.include_test_fixtures,
        )
        print(f"reconcile: matched={result['matched']} "
              f"differences={len(result['differences'])}")
        for d in result["differences"]:
            print(f"  {d}")
        return 0 if not result["differences"] else 2

    trades_dir = Path(args.trades_dir)
    print(f"loading trades from {trades_dir}")
    records = load_records(trades_dir)
    print(f"  {len(records)} records across "
          f"{records['_source_file'].nunique() if not records.empty else 0} files")

    decisions = to_decisions(records)
    exits = to_exits(records)
    closed = to_closed_trades(records)
    ticks = to_ticks(records)

    print(f"  decisions: {len(decisions)}  exits: {len(exits)}  "
          f"closed (joined): {len(closed)}  ticks: {len(ticks)}")

    # Phase 7.4 — ledger-based reports. These run alongside the
    # legacy per-trade jsonl analysis; both views are useful while
    # the migration from daily_summary-driven to ledger-driven
    # analysis is in flight.
    ledger_path = Path(args.ledger)
    if ledger_path.exists():
        trades = build_canonical_trade_table(ledger_path)
        if not trades.empty:
            _print_section("Ledger — by entry_trigger",
                            report_by_entry_trigger(trades))
            _print_section("Ledger — by instrument_class",
                            report_by_instrument_class(trades))
            _print_section("Ledger — by ADV tier",
                            report_by_adv_tier(trades))
            _print_section("Ledger — by spread bucket",
                            report_by_spread_bucket(trades))
            _print_section("Ledger — MFE/MAE distribution",
                            report_mfe_mae_distribution(trades))
            _print_section("Ledger — stop slippage",
                            report_stop_slippage(trades))
            _print_section("Ledger — PnL ex-top-winners",
                            report_ex_top_winners(trades))
            _print_section("Ledger — rescreen ablation",
                            report_rescreen_ablation(trades))

    _print_section("Slot-index alpha (does signal_strength rank predict?)",
                    slot_alpha(closed))
    _print_section("Gate marginal-pass (does just-above-threshold win less?)",
                    gate_marginal_pass(closed))
    _print_section("Exit reason breakdown",
                    exit_reason_breakdown(closed))
    _print_section("MFE / MAE percentiles by exit reason",
                    mfe_mae_distribution(closed))
    _print_section("Slippage summary (entry fill vs candidate close)",
                    slippage_summary(records))
    _print_section("Drawdown depth before stop_hit",
                    drawdown_before_stop(ticks, closed))
    _print_section("Drawdown depth on eventual winners (target_hit)",
                    runup_before_target(ticks, closed))
    _print_section("Hold-duration profile by exit reason",
                    hold_duration_profile(closed))
    _print_section("Gap-at-open vs realized P&L",
                    gap_at_open_vs_outcome(records, closed))

    print()
    print("Tip: import this module from a notebook for richer plots —")
    print("     records / decisions / exits / closed / ticks are all DataFrames.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
