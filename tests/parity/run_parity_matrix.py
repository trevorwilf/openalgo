"""Phase 9 parity matrix — runs run_parity.py under every flag combination.

Each matrix row sets a specific combination of feature flags and
invokes `run_parity.py` in a fresh subprocess. Running in a fresh
process is important: the Phase 0 fixtures are frozen snapshots, and
some service modules cache state at import time. A subprocess
guarantees each row sees a clean import graph.

The fixtures themselves exercise code paths that are mostly
flag-agnostic (pure validation, schedule computation, timestamp
conversion, fixture dict lookups). So every row should pass
byte-identically — that is the canary invariant.

Expected behavior::

    python tests/parity/run_parity_matrix.py
    → every row passes 7/7

Any failure in any row is a refactor regression and must block the
merging PR. The ``parity-v2`` CI job runs this script with no
``continue-on-error``.

Matrix
------
Cumulative: each row is a superset of the flags from the previous,
so the final row has every flag on. That models the canary rollout
order documented in docs/refactor/canary-runbook.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_PARITY = REPO_ROOT / "tests" / "parity" / "run_parity.py"


# Cumulative matrix — each subsequent row enables one more flag.
MATRIX: list[tuple[str, dict[str, str]]] = [
    ("baseline-all-off", {}),
    (
        "INSTRUMENT_CORE_V2",
        {"INSTRUMENT_CORE_V2": "1"},
    ),
    (
        "+ RESOLVER_V2",
        {"INSTRUMENT_CORE_V2": "1", "RESOLVER_V2": "1"},
    ),
    (
        "+ VENUE_SESSION_V2",
        {
            "INSTRUMENT_CORE_V2": "1",
            "RESOLVER_V2": "1",
            "VENUE_SESSION_V2": "1",
        },
    ),
    (
        "+ WEBSOCKET_INSTRUMENT_V2",
        {
            "INSTRUMENT_CORE_V2": "1",
            "RESOLVER_V2": "1",
            "VENUE_SESSION_V2": "1",
            "WEBSOCKET_INSTRUMENT_V2": "1",
        },
    ),
    (
        "+ HISTORIFY_INSTRUMENT_ID_V2",
        {
            "INSTRUMENT_CORE_V2": "1",
            "RESOLVER_V2": "1",
            "VENUE_SESSION_V2": "1",
            "WEBSOCKET_INSTRUMENT_V2": "1",
            "HISTORIFY_INSTRUMENT_ID_V2": "1",
        },
    ),
    (
        "+ API_V2 (all flags on)",
        {
            "INSTRUMENT_CORE_V2": "1",
            "RESOLVER_V2": "1",
            "VENUE_SESSION_V2": "1",
            "WEBSOCKET_INSTRUMENT_V2": "1",
            "HISTORIFY_INSTRUMENT_ID_V2": "1",
            "API_V2": "1",
        },
    ),
]

# Every flag the matrix is aware of. Scrubbed from the inherited env
# in each subprocess call so one row's flags never leak into the next.
_ALL_FLAGS = {
    "INSTRUMENT_CORE_V2",
    "RESOLVER_V2",
    "VENUE_SESSION_V2",
    "WEBSOCKET_INSTRUMENT_V2",
    "HISTORIFY_INSTRUMENT_ID_V2",
    "API_V2",
}


def _build_env(flags: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    for name in _ALL_FLAGS:
        env.pop(name, None)
    env.update(flags)
    return env


def run_row(label: str, flags: dict[str, str]) -> tuple[bool, float, str]:
    """Run `run_parity.py` with the given flag env. Returns
    (passed, duration_s, combined_stdout_stderr)."""
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(RUN_PARITY)],
        cwd=str(REPO_ROOT),
        env=_build_env(flags),
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, duration, output


def main() -> int:
    print("=" * 72)
    print("Phase 9 parity matrix")
    print("=" * 72)
    total_fail = 0
    rows_summary: list[tuple[str, str, float]] = []

    for label, flags in MATRIX:
        flag_summary = ", ".join(sorted(f"{k}={v}" for k, v in flags.items())) or "(none)"
        print(f"\n-- {label} ---- flags: {flag_summary}")
        ok, duration, output = run_row(label, flags)
        # Print the run_parity output verbatim so CI logs are useful.
        for line in output.splitlines():
            print(f"   {line}")
        status = "PASS" if ok else "FAIL"
        rows_summary.append((label, status, duration))
        if not ok:
            total_fail += 1

    print("\n" + "=" * 72)
    print(f"{'row':<35}{'status':<8}{'duration'}")
    print("-" * 72)
    for label, status, duration in rows_summary:
        print(f"{label:<35}{status:<8}{duration:.2f}s")
    print("=" * 72)

    if total_fail:
        print(f"\n{total_fail} / {len(MATRIX)} rows failed")
        return 1
    print(f"\nAll {len(MATRIX)} rows passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
