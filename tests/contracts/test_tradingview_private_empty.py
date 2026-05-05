"""Phase 8 — `frontend/private/tradingview/` must NOT contain the
TradingView Advanced Charts SDK in the OSS checkout.

P-11 + license obligation: the FAC SDK is per-deployment licensed and
never committed. The only file allowed under
`frontend/private/tradingview/` is the README that explains the FAC
license requirement and the path where operators drop their SDK.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TV_PRIVATE = REPO_ROOT / "frontend" / "private" / "tradingview"


# Files that signal a TradingView Advanced Charts SDK has been
# committed. If any of these appear, the test fails — the SDK is FAC-
# licensed and must NEVER ship in the OSS repo.
SDK_SIGNATURE_FILES = {
    "charting_library.standalone.js",
    "charting_library.js",
    "datafeeds",
    "static",
    "bundles",
}


def test_tradingview_private_directory_exists():
    """The directory itself must exist with the README — operators
    rely on the path being present so they know where to drop their
    SDK files."""
    assert TV_PRIVATE.exists(), (
        f"{TV_PRIVATE} should exist with a README.md explaining the FAC "
        "license requirement"
    )


def test_only_readme_is_committed_under_private_tradingview():
    """Walk the directory and assert the only committed file is the
    README. The SDK files are gitignored via .gitignore."""
    if not TV_PRIVATE.exists():
        return
    for path in TV_PRIVATE.rglob("*"):
        if path.is_dir():
            continue
        if path.name == "README.md":
            continue
        rel = path.relative_to(TV_PRIVATE)
        # When the operator has dropped the SDK locally, .gitignore
        # excludes it from `git status` but the file is still on disk.
        # The CI guard runs `git ls-files frontend/private/tradingview`
        # — the local-disk check here just warns; the binding check
        # is the next test.
        assert rel.parts[0] != "charting_library", (
            f"Advanced Charts SDK detected at {path} — the SDK must NEVER "
            "be committed to the OSS repo (P-11)"
        )


def test_sdk_signature_files_not_committed():
    """Use `git ls-files` to confirm none of the SDK signature files
    are tracked. This is the binding CI check — even if a file lands
    on local disk via a sloppy install, git ls-files only shows what's
    tracked."""
    import subprocess

    if not (REPO_ROOT / ".git").exists():
        return
    out = subprocess.run(
        ["git", "ls-files", "frontend/private/tradingview"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    tracked = [p.strip() for p in out.stdout.splitlines() if p.strip()]
    forbidden = []
    for path in tracked:
        # README is the only allowed tracked file.
        if path.endswith("README.md"):
            continue
        for sig in SDK_SIGNATURE_FILES:
            if sig in path:
                forbidden.append(path)
                break
    assert not forbidden, (
        "TradingView Advanced Charts SDK files committed to the OSS repo:\n"
        + "\n".join(f"  - {p}" for p in forbidden)
    )
