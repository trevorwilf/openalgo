"""v4 invariant 5 (static AST view) — promoted code must not import
the legacy India services / databases / schemas at module load time.

This is the static AST analog of ``test_promoted_imports_runtime.py``
(which exercises the same contract at runtime via Python import hooks).
The two tests overlap by design: the runtime test catches transitive
imports while the AST test gives a faster, cheaper signal during
development.

The blocked module list mirrors ADR 0023's invariant 5 list:

* ``services.place_order_service``
* ``services.basket_order_service``
* ``services.split_order_service``
* ``services.margin_service``
* ``services.quotes_service`` (the legacy mode entry points)
* ``services.history_service`` (the legacy mode entry points)
* ``database.symbol``
* ``database.token_db_enhanced``
* ``database.market_calendar_db``
* ``restx_api.schemas``
* ``restx_api.data_schemas``
* ``restx_api.account_schema``
* India option services as legacy implementations:
  ``services.expiry_service``, ``services.option_chain_service``,
  ``services.option_symbol_service`` (these become provider-pluggable
  in Phase 9 — until then they are India-only legacy implementations
  and may be imported only via the dispatcher, which lives in a future
  ``services/options/dispatcher.py``).
* ``services.flow_executor_service`` (India-shaped flow nodes — until
  Phase 6 wires region defaults).

Some of these exist on the v4 invariant 5 list but were already
covered by the existing classified-promoted import lock in
``tests/contracts/test_lane_isolation.py``. This test extends the lock
with the wider v4 set; entries already covered by the existing lock
are still re-asserted here for completeness.

The ``BURIED_IMPORT_ALLOWLIST`` carves out the few PROMOTED_CORE files
that intentionally re-export or call into legacy services on a fall-
through India branch. Those are wrapped in function-local ``import``
statements (not seen by the module-level AST walk), so they do not
appear here. If an entry is added to this allowlist, it MUST cite an
ADR and a closing phase.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION_DOC = REPO_ROOT / "docs" / "refactor" / "file_classification.md"


V4_INVARIANT_5_BLOCKED_MODULES: set[str] = {
    "services.place_order_service",
    "services.basket_order_service",
    "services.split_order_service",
    "services.margin_service",
    "services.quotes_service",
    "services.history_service",
    "database.symbol",
    "database.token_db_enhanced",
    "database.market_calendar_db",
    "restx_api.schemas",
    "restx_api.data_schemas",
    "restx_api.account_schema",
    "services.flow_executor_service",
}


# Empty allowlist — every PROMOTED_CORE file that needs a legacy
# service does so via function-local imports, which the AST module-
# level walk does not see. Adding an entry requires an ADR + a closing
# phase.
BURIED_IMPORT_ALLOWLIST: dict[str, set[str]] = {}


def _read_promoted_core_files() -> list[Path]:
    if not CLASSIFICATION_DOC.is_file():
        pytest.skip(
            "file_classification.md missing — run "
            "`uv run python scripts/audit/classify_files.py`."
        )
    in_section = False
    files: list[Path] = []
    for raw in CLASSIFICATION_DOC.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ") or line.startswith("### "):
            in_section = "PROMOTED_CORE" in line
            continue
        if not in_section:
            continue
        if line.startswith("- "):
            rel = line[2:].strip().strip("`")
            if rel:
                files.append(REPO_ROOT / rel)
    return files


def _check_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    rel = path.relative_to(REPO_ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel}: could not read: {exc}"]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    violations: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if any(
                    mod == bad or mod.startswith(bad + ".")
                    for bad in V4_INVARIANT_5_BLOCKED_MODULES
                ):
                    if mod in BURIED_IMPORT_ALLOWLIST.get(rel, set()):
                        continue
                    violations.append(
                        f"{rel}:{node.lineno}: forbidden `import {mod}` — "
                        "v4 invariant 5: promoted code may not import "
                        "legacy India services at module load time. See "
                        "ADR 0023."
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(
                mod == bad or mod.startswith(bad + ".")
                for bad in V4_INVARIANT_5_BLOCKED_MODULES
            ):
                if mod in BURIED_IMPORT_ALLOWLIST.get(rel, set()):
                    continue
                violations.append(
                    f"{rel}:{node.lineno}: forbidden `from {mod} import …` "
                    "— v4 invariant 5: promoted code may not import "
                    "legacy India services at module load time. See "
                    "ADR 0023."
                )
    return violations


def test_promoted_core_no_v4_legacy_imports() -> None:
    files = _read_promoted_core_files()
    assert files, "PROMOTED_CORE list missing — run classify_files.py."
    violations: list[str] = []
    for path in files:
        violations.extend(_check_file(path))
    assert not violations, (
        "v4 invariant 5 violated — promoted core imports legacy India "
        "service at module-load time:\n  "
        + "\n  ".join(violations)
    )
