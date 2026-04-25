"""Tests for the literal scanner introduced in Phase 1 (ADR 0006).

Exercises ``_literal_violations_in_file`` with synthetic source files
written into ``tmp_path`` so the test does not depend on the live
state of the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.contracts import test_lane_isolation as lane_iso


def _write_source(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_clean_file_has_no_violations(tmp_path: Path, monkeypatch) -> None:
    """A file with no India literals reports no violations."""
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    src = _write_source(
        tmp_path,
        "clean.py",
        '''"""A clean module."""\n\nVALUE = "regular_session"\n''',
    )
    assert lane_iso._literal_violations_in_file(src) == []


def test_docstring_does_not_trigger(tmp_path: Path, monkeypatch) -> None:
    """Module/class/function docstrings are exempt — only string Constants
    elsewhere count toward AST hits.

    The regex pass still covers source lines that aren't docstrings.
    """
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    body = (
        '"""This module talks about NSE and the IST timezone in its docs.\n'
        'Asia/Kolkata is mentioned in the docstring."""\n'
        'VALUE = "regular_session"\n'
    )
    src = _write_source(tmp_path, "docs.py", body)
    # The docstring lines hit the regex pass (it doesn't strip
    # docstrings), so we expect at least one finding from the regex
    # path. The point is: no AST-Constant hit.
    findings = lane_iso._literal_violations_in_file(src)
    assert all("string constant" not in f for f in findings)


def test_string_constant_with_literal_triggers(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    src = _write_source(
        tmp_path,
        "bad.py",
        'EXCHANGE = "NSE"\n',
    )
    findings = lane_iso._literal_violations_in_file(src)
    assert any("'NSE'" in f for f in findings)


def test_substring_match_is_not_flagged(tmp_path: Path, monkeypatch) -> None:
    """Identifier-like literals are matched on word boundaries so
    `MISC` does not trip on `MIS`, `INSPIRE` does not trip on `INR`."""
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    src = _write_source(
        tmp_path,
        "edges.py",
        'X = "MISC"\nY = "INSPIRE"\nZ = "ENGLISH"\n',
    )
    assert lane_iso._literal_violations_in_file(src) == []


def test_currency_symbol_triggers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    src = _write_source(
        tmp_path,
        "money.py",
        # avoid embedding the literal here would defeat the test, so
        # just write an f-string that contains the rupee glyph.
        'TEMPLATE = f"Total: ₹{amount}"\n',
    )
    findings = lane_iso._literal_violations_in_file(src)
    assert any("₹" in f for f in findings)


def test_allowlist_exempts_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lane_iso, "REPO_ROOT", tmp_path)
    src = _write_source(tmp_path, "exempt.py", 'V = "NSE"\n')
    rel = src.relative_to(tmp_path).as_posix()
    findings = lane_iso._literal_violations_in_file(
        src, allowlist={"NSE": {rel}}
    )
    assert findings == []


def test_promoted_paths_clean_today(monkeypatch) -> None:
    """Inject a known-bad file under restx_api/v2 via PROMOTED_PATH_ROOTS
    indirection and confirm the test fails."""
    fake_root = Path(__file__).parent / "fixtures_phase1_literal"
    fake_root.mkdir(parents=True, exist_ok=True)
    bad = fake_root / "bad_promoted.py"
    bad.write_text('SOMETHING = "Asia/Kolkata"\n', encoding="utf-8")

    monkeypatch.setattr(
        lane_iso,
        "PROMOTED_PATH_ROOTS",
        (fake_root,),
    )
    monkeypatch.setattr(lane_iso, "REPO_ROOT", fake_root.parent.parent.parent)

    findings: list[str] = []
    for path in lane_iso._discover_promoted_python_files():
        findings.extend(lane_iso._literal_violations_in_file(path))
    try:
        assert any("Asia/Kolkata" in f for f in findings), findings
    finally:
        bad.unlink(missing_ok=True)
        try:
            fake_root.rmdir()
        except OSError:
            pass


def test_existing_promoted_paths_pass_literal_scan() -> None:
    """The freshly-created promoted paths in this repo should already
    be clean. This is the regression guard for the contract going
    forward."""
    files = lane_iso._discover_promoted_python_files()
    findings: list[str] = []
    for path in files:
        findings.extend(lane_iso._literal_violations_in_file(path))
    assert not findings, (
        "promoted paths now contain India literals — fix or add to "
        "LITERAL_ALLOWLIST with a TODO referencing the removing phase:\n  "
        + "\n  ".join(findings)
    )
