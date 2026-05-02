"""Phase 9 v5 — India v1→v2 cutover state contract.

The v5 prompt's Phase 9 calls for default-flipping
``API_V2_<BROKER>=true`` for India brokers that have completed
Phase 8-bis (per-broker translator + parity harness). v5 ships
the deprecation announcement (Phase 8) and the cutover
infrastructure (this phase) but **does not** flip the default ON
because the Phase 8-bis per-broker work is the gating condition.

This contract test:

* Pins the safe-state assumption that no India broker has been
  flipped to v2-default-ON without a translator and parity harness.
* Pins the dual-lane parity runner mode (``--lane v1|v2``) exists.
* Pins the deprecation schedule v5 additions.
* Pins that the legacy compatibility shims marked "removed in v5"
  are actually gone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_v2_india_brokers_default_off(monkeypatch):
    """Until Phase 8-bis per-broker translators land, every India
    broker's `API_V2_<BROKER>` flag must default OFF.

    Operators can flip individual brokers via env once their
    translator + parity harness are merged.
    """
    from utils.feature_flags import is_enabled

    for broker in ("zerodha", "angel", "dhan", "fyers", "upstox"):
        flag = f"API_V2_{broker.upper()}"
        monkeypatch.delenv(flag, raising=False)
        assert is_enabled(flag) is False, (
            f"{flag} must default to OFF in v5; per-broker flip is "
            "Phase 8-bis work"
        )


def test_run_parity_supports_lane_filter():
    """The parity runner must accept --lane v1 / --lane v2."""
    cmd = [sys.executable, str(REPO_ROOT / "tests" / "parity" / "run_parity.py")]
    for lane in ("v1", "v2"):
        result = subprocess.run(
            cmd + ["--lane", lane],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"parity runner --lane {lane} failed: {result.stdout}\n{result.stderr}"
        )
        assert f"lane={lane}" in result.stdout, (
            f"parity runner --lane {lane} did not emit the lane suffix; "
            f"output: {result.stdout}"
        )


def test_legacy_fallback_exchanges_alias_is_gone():
    """v5 Phase 2 removed the deprecated alias. Verify import-by-name.

    The file was relocated in v9-bis to ``frontend/src/india_legacy/lib/``.
    """
    text = (
        REPO_ROOT
        / "frontend"
        / "src"
        / "india_legacy"
        / "lib"
        / "legacy_fallback_exchanges.ts"
    ).read_text(encoding="utf-8")
    assert "INDIA_LEGACY_FALLBACK_EXCHANGES" in text, (
        "the canonical name must still be exported"
    )
    # The deprecated alias is actually removed — the file should not
    # have a re-export of `LEGACY_FALLBACK_EXCHANGES`.
    assert "export const LEGACY_FALLBACK_EXCHANGES" not in text, (
        "deprecated alias must be removed (v5 Phase 2)"
    )


def test_make_format_currency_is_gone():
    """v5 Phase 2 removed makeFormatCurrency from lib/utils.ts."""
    text = (REPO_ROOT / "frontend" / "src" / "lib" / "utils.ts").read_text(
        encoding="utf-8"
    )
    assert "export function makeFormatCurrency" not in text, (
        "makeFormatCurrency must be removed (v5 Phase 2)"
    )


def test_v1_lane_guard_still_present():
    """v1 lane guard remains in place during the sunset period.

    Phase 9-bis-physical (T-23 Group D) relocated the guard to
    market_regions/india/legacy_v1/restx_api/_v1_lane_guard.py;
    restx_api/__init__.py imports `enforce_india_only` from the new
    location and wires it into the api_v1_bp `before_request` hook.
    """
    p = (
        REPO_ROOT
        / "market_regions"
        / "india"
        / "legacy_v1"
        / "restx_api"
        / "_v1_lane_guard.py"
    )
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "enforce_india_only" in text


def test_deprecation_schedule_lists_v5_additions():
    """v5 additions are recorded in the deprecation schedule."""
    text = (
        REPO_ROOT / "docs" / "refactor" / "deprecation-schedule.md"
    ).read_text(encoding="utf-8")
    assert "v5 additions" in text or "v5 Phase 9" in text
    assert "OPENALGO_V1_SUNSET_DATE" in text
