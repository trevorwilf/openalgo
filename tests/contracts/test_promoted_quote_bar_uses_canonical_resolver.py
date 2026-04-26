"""Phase 5 v4 (ADR 0023, ADR 0018) — promoted quote and bar dispatch
must route every instrument lookup through the canonical resolver
(:func:`services.instrument_resolution.resolve_instrument`), never
through the legacy ``database.token_db_enhanced`` / ``database.symbol``
helpers.

Static AST scan: ``restx_api/v2/quotes.py`` and
``restx_api/v2/bars.py`` may not import either legacy module at
module-load time. Per-line lazy imports inside the legacy India
fallback branch are allowed (and not seen by this AST walk) — the
runtime import lock plus the v4 invariant 5 import contract together
cover them.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PROMOTED_FILES_TO_SCAN = [
    REPO_ROOT / "restx_api" / "v2" / "quotes.py",
    REPO_ROOT / "restx_api" / "v2" / "bars.py",
]

LEGACY_RESOLVER_MODULES = {
    "database.token_db_enhanced",
    "database.symbol",
}


def _has_module_level_legacy_import(path: Path) -> list[str]:
    if not path.is_file():
        return []
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in LEGACY_RESOLVER_MODULES:
                    out.append(f"{path.name}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in LEGACY_RESOLVER_MODULES:
                out.append(f"{path.name}:{node.lineno}: from {mod} import …")
    return out


def test_promoted_quote_bar_files_have_no_module_level_legacy_resolver_import():
    violations: list[str] = []
    for f in PROMOTED_FILES_TO_SCAN:
        violations.extend(_has_module_level_legacy_import(f))
    assert not violations, (
        "Promoted quote/bar dispatch must use the canonical resolver:\n  "
        + "\n  ".join(violations)
    )


def test_canonical_resolver_is_imported_from_quotes_and_bars():
    """Sanity check — the canonical resolver SHOULD appear, either as a
    top-level import or in a module-local helper. Either is fine; we
    just want to confirm the route is wired."""
    for f in PROMOTED_FILES_TO_SCAN:
        text = f.read_text(encoding="utf-8")
        assert (
            "services.instrument_resolution" in text
            or "instrument_resolution" in text
        ), f"{f.name} does not reference the canonical resolver"
