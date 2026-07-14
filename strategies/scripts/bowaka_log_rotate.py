#!/usr/bin/env python3
"""Bowaka v2 — size-based rotation for the watchdog err/out logs.

The strategy/scanner watchdog ``.cmd`` shells redirect stdout/stderr
into ``logs/bowaka_v2_*.out.log`` / ``.err.log``, which grow without
bound (the err log passed 47 MB of mostly-httpx INFO noise before the
httpx level fix). This script rotates any target file over
``--max-mb`` (default 50) into gzipped generations, keeping
``--keep`` (default 3):

    bowaka_v2_strategy.err.log         (live, truncated in place)
    bowaka_v2_strategy.err.log.1.gz    (newest rotated)
    bowaka_v2_strategy.err.log.2.gz
    bowaka_v2_strategy.err.log.3.gz    (oldest, deleted on next shift)

Copytruncate pattern (mirrors bowaka_gate_dump_rotate.py's safety
conventions): the live writer keeps its open append handle across the
rotation — the content is gzip-copied first, THEN the original is
truncated in place. A writer that holds the file exclusively makes
the truncate raise; the file is then skipped gracefully (the copied
.gz temp is discarded so nothing duplicates on the next run). Lines
appended between the copy and the truncate are lost — the standard
copytruncate caveat; run it outside the session window (the operator
schedules this via Task Scheduler on weekends).

Usage:
    uv run python strategies/scripts/bowaka_log_rotate.py
        [--max-mb 50] [--keep 3] [--log-dir logs] [--dry-run]
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bowaka_v2_paths as paths

DEFAULT_MAX_MB = 50
DEFAULT_KEEP = 3
TARGET_GLOBS = ("bowaka_v2_*.err.log", "bowaka_v2_*.out.log")


def rotate_file(path: Path, max_bytes: int, keep: int,
                dry_run: bool = False) -> bool:
    """Rotate ``path`` if it exceeds ``max_bytes``. Returns True when
    a rotation happened. Never raises for the expected failure modes
    (locked file, vanished file) — logs to stdout and skips."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= max_bytes:
        return False
    if dry_run:
        print(f"would rotate {path.name} ({size / 1e6:.1f} MB)")
        return False

    # 1. Gzip-copy the current content to a temp file.
    gz_tmp = path.with_name(path.name + ".1.gz.tmp")
    try:
        with open(path, "rb") as src, gzip.open(gz_tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    except OSError as e:
        print(f"skip {path.name}: copy failed ({e})")
        gz_tmp.unlink(missing_ok=True)
        return False

    # 2. Truncate the original IN PLACE (the writer's append handle
    #    stays valid). An exclusive holder makes this raise — skip
    #    gracefully and discard the copy so nothing duplicates.
    try:
        with open(path, "r+b") as fh:
            fh.truncate(0)
    except OSError as e:
        print(f"skip {path.name}: active writer holds it ({e})")
        gz_tmp.unlink(missing_ok=True)
        return False

    # 3. Shift generations only after the rotation is committed.
    oldest = path.with_name(f"{path.name}.{keep}.gz")
    oldest.unlink(missing_ok=True)
    for i in range(keep - 1, 0, -1):
        gen = path.with_name(f"{path.name}.{i}.gz")
        if gen.exists():
            gen.rename(path.with_name(f"{path.name}.{i + 1}.gz"))
    gz_tmp.rename(path.with_name(f"{path.name}.1.gz"))
    print(f"rotated {path.name} ({size / 1e6:.1f} MB -> .1.gz)")
    return True


def rotate_all(log_dir: Path, max_bytes: int, keep: int,
               dry_run: bool = False) -> int:
    """Rotate every matching log in ``log_dir``. Returns the count of
    files rotated."""
    rotated = 0
    for pattern in TARGET_GLOBS:
        for path in sorted(log_dir.glob(pattern)):
            if rotate_file(path, max_bytes, keep, dry_run=dry_run):
                rotated += 1
    return rotated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB,
                    help="rotate files larger than this "
                         "(default %(default)s MB)")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help="gzipped generations to keep "
                         "(default %(default)s)")
    ap.add_argument("--log-dir", type=Path,
                    default=paths.REPO_ROOT / "logs",
                    help="directory holding the watchdog logs "
                         "(default <repo>/logs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would rotate; write nothing")
    args = ap.parse_args(argv)

    if not args.log_dir.is_dir():
        print(f"log dir {args.log_dir} does not exist; nothing to do")
        return 0
    n = rotate_all(args.log_dir, int(args.max_mb * 1e6), args.keep,
                   dry_run=args.dry_run)
    print(f"{n} file(s) rotated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
