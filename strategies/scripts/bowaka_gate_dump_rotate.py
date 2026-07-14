#!/usr/bin/env python3
"""Bowaka v2 — scanner gate-dump rotation + compaction.

The intraday scanner appends one JSONL row per symbol per scan tick to
``scanner_gate_dump.jsonl`` (~90 MB/session), which grows without bound.
This script enforces the retention policy agreed 2026-07-11:

  RAW      keep the most recent ``--keep-sessions`` (default 30) distinct
           session dates in the raw JSONL, rolling.
  ARCHIVE  sessions older than the raw window but on/after the SIP
           cutover (2026-06-04) are compacted to ONE row per
           (session_date, symbol) — the "feature envelope" — in monthly
           parquet files under data/bowaka_v2/gate_dump_archive/.
  DROP     sessions before the SIP cutover are deleted outright: IEX-feed
           era, wrong feature distributions, misleading for calibration.

The envelope keeps everything gate recalibration needs without the
per-tick bulk: per-day feature maxima, the full feature snapshot at the
symbol's best tick (fewest failing gates), per-gate pass counts, and the
prior-day baselines.

Safety:
  * The scanner holds an open append handle on the dump for the whole
    session (07:30–13:30 MT weekdays), so this refuses to run inside
    that window unless --force is given. Run it on weekends/evenings —
    the scheduled task runs Saturday mornings.
  * Archive parquet is written BEFORE the raw file is rewritten; a
    failure between the two just re-archives the same rows next run
    (deduped on session_date+symbol).
  * --dry-run is strictly read-only: classifies and reports, writes
    nothing.

Usage:
    uv run python strategies/scripts/bowaka_gate_dump_rotate.py [--dry-run]
        [--keep-sessions 30] [--cutover 2026-06-04] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bowaka_v2_paths as paths

SIP_CUTOVER_DEFAULT = date(2026, 6, 4)
KEEP_SESSIONS_DEFAULT = 30

# Scanner session window (local MT) during which the dump file has an
# open append handle and must not be rewritten.
SCAN_WINDOW_START_HOUR = 7
SCAN_WINDOW_END_HOUR = 15  # generous tail past the 13:30 scanner exit

_TS_RE = re.compile(r'"ts":\s*"(\d{4}-\d{2}-\d{2})')

# Prior-day baselines are constant within a session; capture once.
_BASELINE_KEYS = ("prior_close", "prior_atr_pct", "ema_slope_prior",
                  "avg_dollar_volume_20d")


def _in_scan_window(now: datetime) -> bool:
    return (now.weekday() < 5
            and SCAN_WINDOW_START_HOUR <= now.hour < SCAN_WINDOW_END_HOUR)


def _line_date(line: str) -> str | None:
    m = _TS_RE.search(line, 0, 60)
    return m.group(1) if m else None


def classify_sessions(dump_path: Path, keep_sessions: int, cutover: date):
    """Pass 1 — stream the dump once, counting records per session date.

    Returns (per_date Counter, retain set, archive set, drop set,
    malformed line count).
    """
    per_date: Counter[str] = Counter()
    malformed = 0
    with open(dump_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            d = _line_date(line)
            if d is None:
                malformed += 1
            else:
                per_date[d] += 1

    all_dates = sorted(per_date)
    cutover_iso = cutover.isoformat()
    # Pre-cutover sessions are dropped unconditionally — the keep window
    # only counts post-cutover sessions.
    eligible = [d for d in all_dates if d >= cutover_iso]
    retain = set(eligible[-keep_sessions:]) if keep_sessions else set()
    archive = {d for d in eligible if d not in retain}
    drop = {d for d in all_dates if d < cutover_iso}
    return per_date, retain, archive, drop, malformed


class _Envelope:
    """Per-(session_date, symbol) accumulator."""

    __slots__ = ("n_scans", "n_pass", "min_failing", "best_key", "best_ts",
                 "best_failing", "best_features", "max_features",
                 "gate_pass", "baselines", "instrument_class")

    def __init__(self) -> None:
        self.n_scans = 0
        self.n_pass = 0
        self.min_failing = None
        self.best_key = None       # (n_failing, -rvol) — lower is better
        self.best_ts = None
        self.best_failing = None
        self.best_features = {}
        self.max_features = {}
        self.gate_pass: Counter[str] = Counter()
        self.baselines = {}
        self.instrument_class = None

    def add(self, rec: dict) -> None:
        self.n_scans += 1
        if rec.get("ok"):
            self.n_pass += 1
        failing = rec.get("failing_gates") or []
        n_fail = len(failing)
        if self.min_failing is None or n_fail < self.min_failing:
            self.min_failing = n_fail

        features = rec.get("features") or {}
        rvol = features.get("rvol_so_far")
        key = (n_fail, -(rvol if isinstance(rvol, (int, float)) else 0.0))
        if self.best_key is None or key < self.best_key:
            self.best_key = key
            self.best_ts = rec.get("ts")
            self.best_failing = ";".join(failing)
            self.best_features = features

        for k, v in features.items():
            if isinstance(v, (int, float)):
                cur = self.max_features.get(k)
                if cur is None or v > cur:
                    self.max_features[k] = v

        for gate, passed in (rec.get("gate_results") or {}).items():
            if passed:
                self.gate_pass[gate] += 1

        if not self.baselines:
            b = rec.get("baselines") or {}
            self.baselines = {k: b.get(k) for k in _BASELINE_KEYS}
        if self.instrument_class is None:
            self.instrument_class = rec.get("instrument_class")

    def row(self, session_date: str, symbol: str) -> dict:
        row = {
            "session_date": session_date,
            "symbol": symbol,
            "instrument_class": self.instrument_class,
            "n_scans": self.n_scans,
            "n_pass": self.n_pass,
            "min_failing_gates": self.min_failing,
            "best_ts": self.best_ts,
            "best_failing_gates": self.best_failing,
        }
        for k, v in self.baselines.items():
            row[k] = v
        for k, v in self.max_features.items():
            row[f"max_{k}"] = v
        for k, v in self.best_features.items():
            row[f"best_{k}"] = v
        for gate, n in self.gate_pass.items():
            row[f"pass_{gate}"] = n
        return row


def rotate(dump_path: Path, archive_dir: Path, keep_sessions: int,
           cutover: date, dry_run: bool) -> int:
    if not dump_path.exists():
        print(f"nothing to do: {dump_path} does not exist")
        return 0

    size_before = dump_path.stat().st_size
    t0 = time.time()
    print(f"gate dump: {dump_path} ({size_before / 1e9:.2f} GB)")
    print(f"policy: keep {keep_sessions} raw sessions, archive back to "
          f"{cutover.isoformat()}, drop earlier")

    per_date, retain, archive, drop, malformed = classify_sessions(
        dump_path, keep_sessions, cutover)
    print(f"pass 1: {sum(per_date.values()):,} records across "
          f"{len(per_date)} sessions ({malformed} unparseable lines, "
          f"retained verbatim) [{time.time() - t0:.0f}s]")

    def _bucket(label: str, dates: set[str]) -> None:
        n = sum(per_date[d] for d in dates)
        span = f"{min(dates)}..{max(dates)}" if dates else "-"
        print(f"  {label:8s} {len(dates):3d} sessions  {n:>10,} records  {span}")

    _bucket("retain", retain)
    _bucket("archive", archive)
    _bucket("drop", drop)

    if dry_run:
        print("dry-run: read-only, nothing written.")
        return 0

    if not archive and not drop:
        print("nothing to rotate out; raw file unchanged.")
        return 0

    # Pass 2 — retained lines stream verbatim to a temp file; archive
    # lines are parsed and folded into envelopes; drop lines are skipped.
    envelopes: dict[tuple[str, str], _Envelope] = {}
    tmp_path = dump_path.with_name(dump_path.name + ".tmp")
    kept = archived = dropped = 0
    with open(dump_path, "r", encoding="utf-8", errors="replace") as src, \
         open(tmp_path, "w", encoding="utf-8", newline="\n") as dst:
        for line in src:
            d = _line_date(line)
            if d is None or d in retain:
                dst.write(line)
                kept += 1
            elif d in archive:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    dst.write(line)  # never silently lose an odd line
                    kept += 1
                    continue
                key = (d, rec.get("symbol", "?"))
                env = envelopes.get(key)
                if env is None:
                    env = envelopes[key] = _Envelope()
                env.add(rec)
                archived += 1
            else:
                dropped += 1
    print(f"pass 2: kept {kept:,}, archived {archived:,}, dropped "
          f"{dropped:,} records [{time.time() - t0:.0f}s]")

    # Write the archive BEFORE touching the raw file.
    if envelopes:
        import pandas as pd

        archive_dir.mkdir(parents=True, exist_ok=True)
        rows = [env.row(d, sym) for (d, sym), env in envelopes.items()]
        df = pd.DataFrame(rows)
        for month, month_df in df.groupby(df["session_date"].str[:7]):
            out = archive_dir / f"gate_envelope_{month}.parquet"
            if out.exists():
                month_df = pd.concat([pd.read_parquet(out), month_df],
                                     ignore_index=True)
                month_df = month_df.drop_duplicates(
                    subset=["session_date", "symbol"], keep="last")
            month_df = month_df.sort_values(
                ["session_date", "symbol"]).reset_index(drop=True)
            ptmp = out.with_name(out.name + ".tmp")
            month_df.to_parquet(ptmp, index=False)
            os.replace(ptmp, out)
            print(f"archive: {out.name} <- {len(month_df):,} envelope rows")

    try:
        os.replace(tmp_path, dump_path)
    except PermissionError:
        tmp_path.unlink(missing_ok=True)
        print("ERROR: raw file is locked (scanner running?); rotation "
              "aborted, original file untouched. Archive rows already "
              "written will dedupe on the next run.")
        return 1

    size_after = dump_path.stat().st_size
    print(f"raw file: {size_before / 1e9:.2f} GB -> {size_after / 1e9:.2f} GB "
          f"(freed {(size_before - size_after) / 1e9:.2f} GB) "
          f"[{time.time() - t0:.0f}s total]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="classify and report only; write nothing")
    ap.add_argument("--keep-sessions", type=int,
                    default=KEEP_SESSIONS_DEFAULT,
                    help="raw sessions to retain (default %(default)s)")
    ap.add_argument("--cutover", type=lambda s: date.fromisoformat(s),
                    default=SIP_CUTOVER_DEFAULT,
                    help="drop (no archive) sessions before this date "
                         "(default %(default)s, the SIP feed cutover)")
    ap.add_argument("--force", action="store_true",
                    help="skip the scan-hours safety guard")
    args = ap.parse_args()

    now = datetime.now()
    if not args.dry_run and not args.force and _in_scan_window(now):
        print(f"REFUSING to run at {now:%a %H:%M} — inside the scanner's "
              f"session window (Mon-Fri {SCAN_WINDOW_START_HOUR:02d}:00-"
              f"{SCAN_WINDOW_END_HOUR:02d}:00 local); the scanner holds an "
              "open handle on the dump. Re-run after hours or use --force.")
        return 2

    return rotate(paths.SCANNER_GATE_DUMP_PATH, paths.GATE_DUMP_ARCHIVE_DIR,
                  args.keep_sessions, args.cutover, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
