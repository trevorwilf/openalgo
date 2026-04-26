"""Phase 0 v3 — assertions over the file classification report.

The classification at ``docs/refactor/file_classification.md`` is the
contract. These tests enforce that:

1. Every classified file exists on disk.
2. No file appears under more than one classification.
3. ``scripts/audit/classify_files.py --check`` reports zero drift on
   the current state.

The classifier itself is the source of truth for the buckets; this
module verifies the report matches the live state.
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs" / "refactor" / "file_classification.md"
CLASSIFIER = REPO_ROOT / "scripts" / "audit" / "classify_files.py"

VALID_BUCKETS = (
    "PROMOTED_CORE",
    "LEGACY_INDIA",
    "REGION_PLUGIN",
    "BROKER_PLUGIN",
    "COMPATIBILITY_SHIM",
)


def _parse_report() -> dict[str, list[str]]:
    text = REPORT.read_text(encoding="utf-8")
    bucket: dict[str, list[str]] = defaultdict(list)
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            current = None
            for b in VALID_BUCKETS:
                if head == b or head.startswith(b + " "):
                    current = b
                    break
        elif current and line.startswith("- `") and line.endswith("`"):
            bucket[current].append(line[3:-1])
    return bucket


def test_classification_report_exists() -> None:
    assert REPORT.is_file(), (
        f"classification report missing at {REPORT}; run "
        "`uv run python scripts/audit/classify_files.py`."
    )


def test_every_classified_file_exists_on_disk() -> None:
    bucket = _parse_report()
    missing: list[str] = []
    for cls, files in bucket.items():
        for rel in files:
            if not (REPO_ROOT / rel).is_file():
                missing.append(f"{cls}: {rel}")
    assert not missing, (
        "Classification report references files that no longer exist:\n  "
        + "\n  ".join(missing)
    )


def test_no_file_in_two_buckets() -> None:
    bucket = _parse_report()
    seen: dict[str, list[str]] = defaultdict(list)
    for cls, files in bucket.items():
        for rel in files:
            seen[rel].append(cls)
    duplicates = {rel: classes for rel, classes in seen.items() if len(classes) > 1}
    assert not duplicates, (
        "Files appear in more than one classification bucket: "
        f"{duplicates}"
    )


def test_classifier_check_mode_reports_zero_drift() -> None:
    """`scripts/audit/classify_files.py --check` must report zero drift —
    every on-disk classifiable file matches the bucket recorded in the
    report. Done in-process to avoid the subprocess startup tax for
    pytest's per-test timeout.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "audit"))
    try:
        import classify_files  # type: ignore[import-not-found]

        bucket_now = classify_files.classify_all()
        bucket_disk = classify_files.parse_report()
        diffs = classify_files.diff_buckets(bucket_disk, bucket_now)
    finally:
        sys.path.pop(0)
    assert not diffs, (
        "Classification drift between rules and report. Either update "
        "the rules YAML or relocate the offending files:\n  "
        + "\n  ".join(diffs)
    )


@pytest.mark.parametrize("bucket", VALID_BUCKETS)
def test_each_bucket_appears_in_report(bucket: str) -> None:
    """Sanity check — the report has a section for every valid bucket
    even if the bucket is empty (REGION_PLUGIN currently has no .py
    files but still gets a section)."""
    text = REPORT.read_text(encoding="utf-8")
    assert f"## {bucket}" in text, f"bucket {bucket!r} missing from report"
