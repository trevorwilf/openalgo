"""Phase 1 — Datafeed Foundation: 1-minute → arbitrary-timeframe resampler.

Pulls 1m bars from DuckDB Historify (or any in-memory frame) and
resamples to any canonical interval via Polars. Gap-aware: missing
buckets are simply absent from the output (no synthetic zero-volume
bars unless the caller asks via `forward_fill_ohlc=True`).

Acceptance target (HANDOFF C1-T7): 1y of 1m AAPL → 1d in <500ms.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

try:
    import polars as pl  # type: ignore[import-not-found]

    POLARS_AVAILABLE = True
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]
    POLARS_AVAILABLE = False


# Map canonical intervals onto Polars `dynamic_group_by(every=...)` strings.
_POLARS_EVERY: dict[str, str] = {
    "1s": "1s",
    "5s": "5s",
    "15s": "15s",
    "30s": "30s",
    "1m": "1m",
    "2m": "2m",
    "3m": "3m",
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1mo": "1mo",
}


def polars_every(canonical_interval: str) -> str | None:
    """Map a canonical interval to a Polars `every=` argument."""
    return _POLARS_EVERY.get(canonical_interval)


def resample_bars(
    bars: Iterable[dict[str, Any]],
    target_interval: str,
    *,
    forward_fill_ohlc: bool = False,
) -> list[dict[str, Any]]:
    """Resample 1m bars (each {t, o, h, l, c, v, oi}) to `target_interval`.

    - `bars`: iterable of bar dicts. `t` is UTC seconds (int).
    - `target_interval`: canonical token from D-08.
    - `forward_fill_ohlc`: when True, fills empty buckets with the
      previous close (volume=0). Default False (gap-aware).

    Returns a list of bar dicts in the same wire shape, sorted by `t`.
    """
    if not POLARS_AVAILABLE:
        raise RuntimeError(
            "polars is not installed. Install with `uv add polars` to use the bar resampler."
        )

    every = polars_every(target_interval)
    if every is None:
        raise ValueError(f"unsupported interval: {target_interval}")

    rows = list(bars)
    if not rows:
        return []

    df = pl.DataFrame(
        {
            "t": [int(r["t"]) for r in rows],
            "o": [float(r["o"]) for r in rows],
            "h": [float(r["h"]) for r in rows],
            "l": [float(r["l"]) for r in rows],
            "c": [float(r["c"]) for r in rows],
            "v": [float(r["v"]) for r in rows],
            "oi": [float(r["oi"]) if r.get("oi") is not None else None for r in rows],
        }
    ).with_columns(pl.from_epoch(pl.col("t"), time_unit="s").alias("ts"))

    if target_interval == "1m":
        # No-op: input is already 1m. Sort + dedupe by `t`.
        out = df.sort("t").unique(subset=["t"], keep="last")
        return _frame_to_list(out)

    # Use Polars's group_by_dynamic for efficient bucketed aggregation.
    grouped = (
        df.sort("ts")
        .group_by_dynamic("ts", every=every, label="left", closed="left")
        .agg(
            pl.col("o").first().alias("o"),
            pl.col("h").max().alias("h"),
            pl.col("l").min().alias("l"),
            pl.col("c").last().alias("c"),
            pl.col("v").sum().alias("v"),
            pl.col("oi").last().alias("oi"),
        )
        .with_columns(pl.col("ts").dt.epoch(time_unit="s").alias("t"))
    )

    if forward_fill_ohlc:
        grouped = grouped.with_columns(
            pl.col("c").forward_fill().alias("c"),
        ).with_columns(
            pl.col("o").fill_null(pl.col("c")),
            pl.col("h").fill_null(pl.col("c")),
            pl.col("l").fill_null(pl.col("c")),
            pl.col("v").fill_null(0.0),
        )

    return _frame_to_list(grouped)


def _frame_to_list(df: Any) -> list[dict[str, Any]]:
    """Coerce a Polars frame into the chart wire shape (decimal-strings)."""
    rows: list[dict[str, Any]] = []
    for r in df.iter_rows(named=True):
        oi = r.get("oi")
        rows.append(
            {
                "t": int(r["t"]),
                "o": str(r["o"]),
                "h": str(r["h"]),
                "l": str(r["l"]),
                "c": str(r["c"]),
                "v": str(r["v"]),
                "oi": (str(oi) if oi is not None else None),
            }
        )
    rows.sort(key=lambda x: x["t"])
    return rows


__all__ = ["POLARS_AVAILABLE", "polars_every", "resample_bars"]
