"""Phase 0 parity harness runner.

Usage::

    python tests/parity/run_parity.py           # verify against checked-in fixtures
    python tests/parity/run_parity.py generate  # (re)generate fixtures

Exit code 0 on full pass; 1 on any diff or missing fixture.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Ensure repo root on sys.path BEFORE importing tests.parity._common
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.parity import _common  # noqa: E402

HARNESSES = [
    "parity_quote",
    "parity_history",
    "parity_place_order_validation",
    "parity_historify_validate_symbol",
    "parity_market_calendar",
    "parity_strategy_schedule",
    "parity_iv_chart_timestamp",
    # Phase 7 v4 — venue-aware UTC offset for historify aggregation.
    "parity_historify_offset",
    # v5 Phase 4 (ADR 0026 follow-on) — India sandbox provider parity.
    "parity_sandbox_india",
    # v5 Phase 5 (ADR 0027 follow-on) — India options provider parity.
    "parity_options_india",
]


def main(argv: list[str]) -> int:
    mode = "verify"
    if len(argv) > 1:
        if argv[1] == "generate":
            mode = "generate"
        elif argv[1] == "verify":
            mode = "verify"
        else:
            print(f"unknown mode: {argv[1]}")
            return 2

    total_ok = 0
    total_fail = 0
    for name in HARNESSES:
        module = importlib.import_module(f"tests.parity.baseline.{name}")
        ok, messages = _common.run_harness(name, module.generate, mode=mode)
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {name}")
        for msg in messages:
            print(f"         {msg}")
        if ok:
            total_ok += 1
        else:
            total_fail += 1

    print(f"\n{total_ok}/{len(HARNESSES)} passed, {total_fail} failed ({mode} mode)")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
