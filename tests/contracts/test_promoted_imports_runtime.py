"""Phase 1 v3 — runtime import lock for classified PROMOTED_CORE files.

The static import scanner (``test_lane_isolation.py``
``test_classified_promoted_files_have_no_forbidden_imports``) catches
module-level legacy imports. This test catches the same leak through a
*runtime* lens: each PROMOTED_CORE file is imported in a clean
subprocess and ``sys.modules`` is inspected to confirm none of the
forbidden legacy modules were pulled in transitively.

A subprocess per PROMOTED_CORE file would be too slow on Windows
(process startup tax). We instead run a single subprocess that takes
the file list and imports each one, checking ``sys.modules`` after
every import and printing the chain on first violation. The parent
test parses the structured output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs" / "refactor" / "file_classification.md"

# Modules that must never be pulled into a PROMOTED_CORE file's import
# graph (transitively or otherwise) at module-load time. Same list as
# the static lock; runtime catches lazy module-level imports the AST
# walker can't see.
FORBIDDEN_RUNTIME_MODULES: tuple[str, ...] = (
    "utils.constants",
    "database.token_db",
    "database.token_db_enhanced",
    "database.symbol",
    "database.market_calendar_db",
    # Phase 3 (T-20) — services.quotes_service / history_service /
    # place_order_service / basket_order_service / split_order_service
    # were on this list because they imported from utils.constants /
    # database.token_db at module load. After the Phase 3 migration
    # those legacy imports are function-local and the modules
    # themselves are PROMOTED_CORE-classified. Removing them from the
    # runtime forbidden list lets other PROMOTED_CORE files import
    # them without a transitive-legacy violation. The static lane-
    # isolation contract still blocks any new imports of legacy
    # symbols inside these files at module level.
)


def _read_promoted_core() -> list[str]:
    text = REPORT.read_text(encoding="utf-8")
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().startswith("PROMOTED_CORE")
            continue
        if in_section and line.startswith("- `") and line.endswith("`"):
            out.append(line[3:-1])
    return out


def _module_name_for(rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    if rel == "__init__.py":
        return None  # top-level package init
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[: -len(".py")]
    return rel.replace("/", ".")


# Files we cannot import standalone — they require a Flask app context
# or running app initialization. They are still subject to the static
# scanner; runtime check is best-effort.
RUNTIME_IMPORT_SKIPS: frozenset[str] = frozenset(
    {
        # Top-level entry points / scaffolding
        "extensions",
        "limiter",
        # WebSocket and background-thread services that bind sockets
        # at import time
        "services.websocket_service",
        "services.websocket_client",
        "services.market_data_service",
    }
)

# Module-prefix skips: importing any submodule of these package roots
# transitively triggers the parent package's __init__, which lives in
# LEGACY_INDIA territory and unavoidably loads legacy modules.
#
# Today this only applies to ``restx_api.v2`` — the v2 namespaces are
# nested inside the v1 ``restx_api`` package, so importing
# ``restx_api.v2`` (or any of its leaf modules) forces ``restx_api``
# (the v1 init) to load, which eagerly imports v1 namespaces and pulls
# in ``utils.constants`` / ``database.token_db`` / etc. This is a
# structural quirk of the package layout; the static import scanner
# (``test_lane_isolation.py``) covers these files at the AST level and
# is the meaningful guard.
RUNTIME_IMPORT_SKIP_PREFIXES: tuple[str, ...] = (
    "restx_api.",
)


def _candidate_modules() -> list[str]:
    rels = _read_promoted_core()
    out: list[str] = []
    for rel in rels:
        mod = _module_name_for(rel)
        if not mod:
            continue
        if mod in RUNTIME_IMPORT_SKIPS:
            continue
        if any(mod.startswith(prefix) for prefix in RUNTIME_IMPORT_SKIP_PREFIXES):
            continue
        out.append(mod)
    return out


def _subprocess_check(modules: list[str]) -> dict:
    code = (
        "import json, sys, importlib\n"
        "modules = json.loads(sys.stdin.read())\n"
        "forbidden = " + repr(FORBIDDEN_RUNTIME_MODULES) + "\n"
        "violations = []\n"
        "def _reset_forbidden():\n"
        "    for m in list(sys.modules):\n"
        "        if any(m == b or m.startswith(b + '.') for b in forbidden):\n"
        "            sys.modules.pop(m, None)\n"
        "for mod in modules:\n"
        "    # Start each iteration with no forbidden modules cached so a\n"
        "    # leak from an earlier iteration cannot mis-blame the current\n"
        "    # one. The PROMOTED_CORE module under test must not pull any\n"
        "    # of these in at module-load time.\n"
        "    _reset_forbidden()\n"
        "    sys.modules.pop(mod, None)\n"
        "    try:\n"
        "        importlib.import_module(mod)\n"
        "    except Exception as e:\n"
        "        violations.append({'module': mod, 'kind': 'import_error', 'detail': str(e)})\n"
        "        continue\n"
        "    bad = [m for m in forbidden if m in sys.modules]\n"
        "    if bad:\n"
        "        violations.append({'module': mod, 'kind': 'transitive_legacy', 'detail': bad})\n"
        "json.dump({'violations': violations}, sys.stdout)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(modules),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if proc.returncode != 0:
        return {"violations": [{"module": "<subprocess>", "kind": "fatal", "detail": proc.stderr}]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "violations": [
                {"module": "<subprocess>", "kind": "fatal", "detail": f"bad JSON: {exc}; stdout={proc.stdout!r}"}
            ]
        }


def test_promoted_core_modules_have_no_transitive_legacy_imports() -> None:
    """Each PROMOTED_CORE module is imported in a fresh subprocess; if
    any forbidden legacy module ends up in ``sys.modules`` the
    PROMOTED_CORE module is leaking through a transitive dependency.
    """
    modules = _candidate_modules()
    assert modules, (
        "No PROMOTED_CORE modules to test — run "
        "`uv run python scripts/audit/classify_files.py` to regenerate."
    )
    result = _subprocess_check(modules)
    leaks = [
        v for v in result["violations"]
        if v["kind"] == "transitive_legacy"
    ]
    assert not leaks, (
        "Runtime import lock violated — PROMOTED_CORE modules pulled "
        "legacy modules into sys.modules at import time:\n  "
        + "\n  ".join(f"{v['module']} -> {v['detail']}" for v in leaks)
    )


def test_subprocess_did_not_fatally_error() -> None:
    """The subprocess that runs the import probe must succeed; if it
    fatals, the runtime lock loses its meaning."""
    modules = _candidate_modules()
    if not modules:
        pytest.skip("no PROMOTED_CORE modules")
    result = _subprocess_check(modules[:1])  # cheap sanity probe
    fatals = [v for v in result["violations"] if v["kind"] == "fatal"]
    assert not fatals, (
        "Subprocess import probe failed: "
        + "; ".join(f"{v['module']}: {v['detail']}" for v in fatals)
    )
