"""Guard: the rollout runbook is part of the docs surface."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runbook_exists():
    runbook = REPO_ROOT / "docs" / "runbooks" / "promoted-broker-rollout.md"
    assert runbook.is_file()


def test_runbook_mentions_critical_metrics():
    runbook = (
        REPO_ROOT / "docs" / "runbooks" / "promoted-broker-rollout.md"
    ).read_text(encoding="utf-8")
    for metric in [
        "promoted_legacy_fallback_total",
        "rule_rejections_total",
        "instrument_sync_lag_seconds",
    ]:
        assert metric in runbook, f"runbook must reference {metric}"
