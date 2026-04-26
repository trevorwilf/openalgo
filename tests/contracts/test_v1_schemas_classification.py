"""Phase 1 v3 — assert v1 schema modules are stamped LEGACY_INDIA.

The contract:

* ``restx_api.schemas``, ``restx_api.data_schemas``, and
  ``utils.constants`` each declare a top-level
  ``LEGACY_INDIA_COMPATIBILITY = True`` sentinel.
* No file classified ``PROMOTED_CORE`` imports any of those three
  modules at module-load time. Function-local imports inside legacy
  fallback paths are out of scope here (the static
  ``test_classified_promoted_files_have_no_forbidden_imports`` test
  already catches them).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs" / "refactor" / "file_classification.md"

LEGACY_MODULES = (
    "restx_api.schemas",
    "restx_api.data_schemas",
    "utils.constants",
)


@pytest.mark.parametrize("module_name", LEGACY_MODULES)
def test_module_has_legacy_india_compatibility_flag(module_name: str) -> None:
    import importlib

    mod = importlib.import_module(module_name)
    flag = getattr(mod, "LEGACY_INDIA_COMPATIBILITY", None)
    assert flag is True, (
        f"{module_name} must declare LEGACY_INDIA_COMPATIBILITY = True "
        "(Phase 1 v3 requirement). Add the constant to the module."
    )


def _read_promoted_core() -> list[Path]:
    text = REPORT.read_text(encoding="utf-8")
    out: list[Path] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().startswith("PROMOTED_CORE")
            continue
        if in_section and line.startswith("- `") and line.endswith("`"):
            out.append(REPO_ROOT / line[3:-1])
    return out


def _module_imports_at_load_time(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    mods: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def test_no_promoted_core_file_imports_v1_schemas() -> None:
    """Module-load-time check: no PROMOTED_CORE file imports the v1
    schema modules or ``utils.constants``."""
    files = _read_promoted_core()
    assert files, "PROMOTED_CORE list missing"
    bad: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        imports = _module_imports_at_load_time(path)
        for legacy in LEGACY_MODULES:
            if legacy in imports or any(
                imp.startswith(legacy + ".") for imp in imports
            ):
                bad.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()} imports "
                    f"{legacy} at module load time"
                )
    assert not bad, (
        "PROMOTED_CORE files cannot depend on the v1 legacy schemas:\n  "
        + "\n  ".join(bad)
    )
