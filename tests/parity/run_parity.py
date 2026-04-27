"""Phase 0 parity harness runner.

Usage::

    python tests/parity/run_parity.py                    # verify all
    python tests/parity/run_parity.py generate           # (re)generate
    python tests/parity/run_parity.py --lane v1          # v5: v1-lane only
    python tests/parity/run_parity.py --lane v2          # v5: v2-lane only

Exit code 0 on full pass; 1 on any diff or missing fixture.

v5 Phase 9: ``--lane`` mode is a forward-compat scaffold. The
existing harnesses don't differentiate v1 vs v2 (they snapshot
provider behavior, not lane-specific routes); the per-lane parity
work lands in Phase 8-bis when per-broker v2 harnesses
(``parity_v2_<broker>_india``) are added. For now, ``--lane v2``
runs the existing harnesses (which are India-flavored and shared
between lanes) and ``--lane v1`` does the same — both paths return
the same fixtures because the v1/v2 disambiguation is per-broker.
"""

from __future__ import annotations

import argparse
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
    # v5 Phase 6 (ADR 0028 follow-on) — India Chartink screener parity.
    "parity_chartink_india",
]


def _parse_args(argv: list[str]) -> tuple[str, str | None]:
    """Return (mode, lane). lane is None for "all lanes"."""
    parser = argparse.ArgumentParser(
        prog="run_parity.py",
        description="OpenAlgo parity harness runner",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="verify",
        choices=("verify", "generate"),
        help="verify against checked-in fixtures (default) or regenerate them",
    )
    parser.add_argument(
        "--lane",
        choices=("v1", "v2"),
        default=None,
        help="restrict to v1 or v2 lane harnesses (v5 Phase 9 scaffold)",
    )
    ns = parser.parse_args(argv[1:])
    return ns.mode, ns.lane


def main(argv: list[str]) -> int:
    try:
        mode, lane = _parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    # Lane filter: v2-only harnesses have a `parity_v2_` prefix; v1-only
    # would have `parity_v1_`. Today every harness is shared between
    # lanes so both filters return the same set. Phase 8-bis adds
    # per-broker `parity_v2_<broker>_india` harnesses; the runner will
    # then split as expected.
    selected = HARNESSES
    if lane == "v2":
        selected = [n for n in HARNESSES if not n.startswith("parity_v1_")]
    elif lane == "v1":
        selected = [n for n in HARNESSES if not n.startswith("parity_v2_")]

    total_ok = 0
    total_fail = 0
    for name in selected:
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

    lane_suffix = f", lane={lane}" if lane else ""
    print(
        f"\n{total_ok}/{len(selected)} passed, {total_fail} failed "
        f"({mode} mode{lane_suffix})"
    )
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
