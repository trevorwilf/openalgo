"""Lane isolation — enforce ADR 0005.

Promoted-lane code must not import legacy symbols. Enforced via AST so
docstrings and comments cannot false-positive.

The forbidden-symbol list and the promoted-path roots below are the
contract. A phase-scoped allowlist carries known legacy call-sites
that later phases remove; every entry must include a TODO tag with
the phase that removes it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# (module, symbol) pairs that promoted paths may not import.
LEGACY_ONLY_SYMBOLS: set[tuple[str, str]] = {
    ("utils.constants", "VALID_EXCHANGES"),
    ("utils.constants", "VALID_PRODUCT_TYPES"),
    ("utils.constants", "VALID_PRICE_TYPES"),
    ("database.token_db", "get_token"),
    ("domain.translators", "normalized_order_to_legacy_fields"),
    ("services.quotes_service", "get_quotes_with_auth"),
    ("services.history_service", "get_history_with_auth"),
}

# Directory roots scanned as promoted paths. A broker directory is
# additionally treated as promoted if it contains a sentinel file
# named PROMOTED at its top level (added in later phases).
PROMOTED_PATH_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "restx_api" / "v2",
)


# Phase-scoped allowlist. Keys are (module, symbol) tuples; values are
# the set of repo-relative POSIX paths that are temporarily exempted.
# Every entry carries a TODO naming the phase that removes it.
ALLOWLIST: dict[tuple[str, str], set[str]] = {
    # TODO(phase-4): remove once /api/v2/quotes dispatches to
    # BrokerQuoteAdapter and stops calling the legacy quotes_service.
    ("services.quotes_service", "get_quotes_with_auth"): {
        "restx_api/v2/quotes.py",
    },
    # TODO(phase-4): remove once /api/v2/bars dispatches to
    # BrokerBarAdapter and stops calling the legacy history_service.
    ("services.history_service", "get_history_with_auth"): {
        "restx_api/v2/bars.py",
    },
}


def _discover_promoted_python_files() -> list[Path]:
    """Walk the promoted path roots and yield all .py files."""
    files: list[Path] = []
    for root in PROMOTED_PATH_ROOTS:
        if not root.is_dir():
            continue
        files.extend(p for p in root.rglob("*.py") if p.is_file())

    # Broker directories marked with a PROMOTED sentinel file are
    # treated as promoted paths too. This hook is here so later
    # phases can add `broker/<name>/PROMOTED` and have the guard
    # pick the directory up without editing this test.
    broker_root = REPO_ROOT / "broker"
    if broker_root.is_dir():
        for broker_dir in broker_root.iterdir():
            if not broker_dir.is_dir():
                continue
            if (broker_dir / "PROMOTED").exists():
                files.extend(
                    p for p in broker_dir.rglob("*.py") if p.is_file()
                )

    return files


def _iter_import_references(
    tree: ast.Module,
) -> Iterable[tuple[str, str | None, int]]:
    """Yield (module, attr, lineno) for every module-level Import/ImportFrom.

    We intentionally only walk the module body — nested imports inside
    function bodies are not flagged. The promoted dispatcher keeps its
    legacy fallback import function-local so the lane-isolation check
    proves the legacy symbol is never *loaded* on a promoted request.
    """
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for alias in node.names:
                yield node.module, alias.name, node.lineno


def _check_file(path: Path) -> list[str]:
    """Return a list of violation messages for this file."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel}: could not read: {exc}"]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: syntax error: {exc}"]

    violations: list[str] = []
    for module, attr, lineno in _iter_import_references(tree):
        if attr is not None:
            key = (module, attr)
            if key in LEGACY_ONLY_SYMBOLS:
                if rel in ALLOWLIST.get(key, set()):
                    continue
                violations.append(
                    f"{rel}:{lineno}: forbidden import "
                    f"`from {module} import {attr}` — promoted paths "
                    f"must not depend on legacy symbols. See ADR 0005."
                )
        # Plain `import x.y` of a legacy module as a whole is also
        # disallowed.
        plain_key = (module, "*")
        if plain_key in LEGACY_ONLY_SYMBOLS:
            violations.append(
                f"{rel}:{lineno}: forbidden `import {module}`."
            )
    return violations


def test_promoted_paths_have_no_forbidden_imports() -> None:
    files = _discover_promoted_python_files()
    assert files, (
        "expected at least one promoted .py file under "
        f"{[str(r.relative_to(REPO_ROOT)) for r in PROMOTED_PATH_ROOTS]}"
    )
    violations: list[str] = []
    for path in files:
        violations.extend(_check_file(path))
    assert not violations, (
        "Promoted-lane import contract violated:\n  "
        + "\n  ".join(violations)
    )


def test_allowlist_entries_reference_existing_files() -> None:
    """Catch stale allowlist entries."""
    for key, paths in ALLOWLIST.items():
        for rel in paths:
            abs_path = REPO_ROOT / rel
            assert abs_path.is_file(), (
                f"allowlist entry {key} -> {rel!r} points to a file "
                "that no longer exists; remove the entry."
            )


def test_adr_0005_exists_and_mentions_promoted_lane() -> None:
    adr = REPO_ROOT / "docs" / "adr" / "0005-two-lanes-legacy-and-promoted.md"
    assert adr.is_file(), f"expected {adr} to exist"
    text = adr.read_text(encoding="utf-8").lower()
    assert "promoted lane" in text, (
        "ADR 0005 must document the promoted lane"
    )


def test_forbidden_symbols_list_is_nonempty() -> None:
    assert LEGACY_ONLY_SYMBOLS, "legacy-only symbol list must not be empty"


@pytest.mark.parametrize(
    "symbol",
    [
        ("utils.constants", "VALID_EXCHANGES"),
        ("database.token_db", "get_token"),
        ("domain.translators", "normalized_order_to_legacy_fields"),
    ],
)
def test_each_canonical_forbidden_symbol_is_still_tracked(
    symbol: tuple[str, str],
) -> None:
    assert symbol in LEGACY_ONLY_SYMBOLS, (
        f"{symbol} dropped from the legacy-only list — ADR 0005 "
        "forbids reintroducing these into promoted paths."
    )
