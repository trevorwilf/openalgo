"""Lane isolation — enforce ADR 0005 + ADR 0006.

Promoted-lane code must not import legacy symbols (ADR 0005) and must
not embed India-specific literals (ADR 0006). Both checks are enforced
via AST so docstrings and comments cannot false-positive.

The forbidden-symbol list, the literal list, and the promoted-path
roots below are the contract. A phase-scoped allowlist carries known
legacy call-sites that later phases remove; every entry must include a
TODO tag with the phase that removes it.
"""

from __future__ import annotations

import ast
import re
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
# Allowlist is empty as of Phase 4. The import invariant is now fully
# enforced: every forbidden legacy symbol is loaded only on the
# legacy-fallback branch, inside a function body, where the AST check
# (module-level only) does not see it.
ALLOWLIST: dict[tuple[str, str], set[str]] = {}


# India-specific string literals that may not appear in promoted-lane
# Python source (per ADR 0006). The check is performed both at the AST
# level (string Constants) and via a coarse regex pass to catch any
# non-AST cases (e.g. raw string-formatting templates).
#
# Phase 0 of v3 widens the set with BCD, NSE_INDEX, BSE_INDEX, lakh,
# crore, Cr, L (rupee abbreviations). The "Cr" / "L" entries use the
# same word-boundary regex as the alphanumerics so identifiers like
# "Crash" or "Local" do not trip the scanner.
INDIA_LITERALS: tuple[str, ...] = (
    "Asia/Kolkata",
    "IST",
    "NSE",
    "NFO",
    "BSE",
    "BFO",
    "MCX",
    "CDS",
    "BCD",
    "MIS",
    "CNC",
    "NRML",
    "DDMMMYY",
    "CE",
    "PE",
    "₹",  # ₹
    "INR",
    "NSE_INDEX",
    "BSE_INDEX",
    "lakh",
    "crore",
    "Cr",
    "L",
)


# Phase-scoped literal allowlist. Keys are India literal strings;
# values are sets of repo-relative POSIX paths exempted. Every entry
# must include a TODO line in this file naming the phase that removes
# it.
#
# TODO(v8 Phase 1-bis — deltaexchange v1-compat cleanup): the
# entries below are India-shaped literals embedded in deltaexchange's
# v1-compat layer that survived the T-30 india->crypto migration:
#   * CE / PE — Delta's actual options instrumenttype values
#     (Delta uses the same suffix convention for call/put). These
#     are written into SymToken.instrumenttype during master-contract
#     ingest and read back when serving the options chain.
#   * CNC / NRML — used as v1-shape product codes for spot vs.
#     derivatives. The v1 UI reads these verbatim. Cleanup needs a
#     coordinated v1 OrderBook + Position table change to introduce
#     CRYPTO_SPOT / CRYPTO_DERIVATIVE product codes.
#   * Asia/Kolkata — used for "today" cutoff in order history.
#     Should switch to UTC (or the venue's timezone via the venue
#     session service) once the order-book filter is updated.
#   * NSE — default exchange string for malformed holdings. Should
#     be CRYPTO.
#   * INR — appears once in order_api.py:271. Should come from the
#     venue's currency declaration.
# The cleanup ships in v8 Phase 1-bis as a coordinated v1-UI +
# delta-mapping change. Until then these are exempted so the
# lane-isolation gate runs green.
_DELTA_V1_COMPAT_FILES: set[str] = {
    "broker/deltaexchange/api/data.py",
    "broker/deltaexchange/api/order_api.py",
    "broker/deltaexchange/database/master_contract_db.py",
    "broker/deltaexchange/mapping/order_data.py",
    "broker/deltaexchange/mapping/transform_data.py",
}
LITERAL_ALLOWLIST: dict[str, set[str]] = {
    "CE": set(_DELTA_V1_COMPAT_FILES),
    "PE": set(_DELTA_V1_COMPAT_FILES),
    "CNC": set(_DELTA_V1_COMPAT_FILES),
    "NRML": set(_DELTA_V1_COMPAT_FILES),
    "Asia/Kolkata": set(_DELTA_V1_COMPAT_FILES),
    "NSE": set(_DELTA_V1_COMPAT_FILES),
    "INR": set(_DELTA_V1_COMPAT_FILES),
}


# Substrings that appear in many false-positive contexts (e.g. base64
# blobs, identifiers like "MISC"). The literal scanner only counts a
# whole-word/standalone-token hit, never a substring inside a larger
# identifier. The regex below is anchored on word-class boundaries.
_LITERAL_BOUNDARY_PATTERNS: dict[str, re.Pattern[str]] = {}


def _literal_pattern(literal: str) -> re.Pattern[str]:
    """Cache compiled boundary patterns per literal.

    Identifier-like literals (alphanum + underscore) get a strict
    word-boundary regex that also excludes a leading ``.``, so attribute
    access like ``Currency.INR`` or ``Venue.NSE`` does not trip the
    scanner. The rupee abbreviations ``L`` and ``Cr`` are even
    narrower: they only match when immediately preceded by a digit
    (the ``₹1.5L`` pattern), so ``P&L`` and identifiers like
    ``Crash`` / ``Local`` do not trip.
    """
    pat = _LITERAL_BOUNDARY_PATTERNS.get(literal)
    if pat is not None:
        return pat
    if literal in {"L", "Cr"}:
        # Rupee abbreviation pattern — must follow a digit.
        pat = re.compile(rf"\d{re.escape(literal)}(?![A-Za-z0-9_])")
    elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", literal):
        # Exclude `.NAME` (attribute access) and `NAME` preceded by an
        # alphanumeric or underscore; trailing word boundary as before.
        pat = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(literal)}(?![A-Za-z0-9_])")
    else:
        pat = re.compile(re.escape(literal))
    _LITERAL_BOUNDARY_PATTERNS[literal] = pat
    return pat


def _discover_promoted_python_files() -> list[Path]:
    """Walk the promoted path roots and yield all .py files.

    Broker directories are treated as promoted if either:

    - a ``PROMOTED`` sentinel file exists at the directory root, OR
    - the directory's ``plugin.json`` declares ``supported_regions``
      with any value other than ``india`` (Phase 8 auto-discovery).
    """
    import json

    files: list[Path] = []
    for root in PROMOTED_PATH_ROOTS:
        if not root.is_dir():
            continue
        files.extend(p for p in root.rglob("*.py") if p.is_file())

    broker_root = REPO_ROOT / "broker"
    if broker_root.is_dir():
        for broker_dir in broker_root.iterdir():
            if not broker_dir.is_dir():
                continue
            is_promoted = False
            if (broker_dir / "PROMOTED").exists():
                is_promoted = True
            else:
                plugin = broker_dir / "plugin.json"
                if plugin.is_file():
                    try:
                        data = json.loads(plugin.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}
                    regions = data.get("supported_regions") or []
                    if isinstance(regions, list) and regions and "india" not in [
                        str(r).lower() for r in regions
                    ]:
                        is_promoted = True
            if is_promoted:
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


# ---------------------------------------------------------------------------
# Phase 0 v3 — classified-promoted import lock (HARD fail).
# Reads docs/refactor/file_classification.md and forbids any
# PROMOTED_CORE file from importing from a wider blocklist than the
# original LEGACY_ONLY_SYMBOLS list. The named compatibility shims are
# the only sanctioned bridges.
# ---------------------------------------------------------------------------

CLASSIFIED_FORBIDDEN_MODULES: set[str] = {
    "utils.constants",
    "database.token_db",
    "database.token_db_enhanced",
    "database.symbol",
    "database.market_calendar_db",
    # Phase 3 (T-20): the v1-lane order/quote/history/depth/margin/
    # basket/smart-order/split-order services were on this list because
    # they imported `utils.constants.VALID_*` and other legacy bits at
    # module level. After Phase 3 those imports are function-local,
    # the modules themselves are PROMOTED_CORE-classified, and the
    # static + runtime import locks confirm load-time cleanliness.
    # They are removed from this list so any other PROMOTED_CORE file
    # (e.g. an `/api/v2` route that wants to delegate to the v1
    # implementation during the operator-controlled v1 sunset window)
    # can call them without tripping the contract test. Their lazy
    # legacy imports remain confined to call paths and run only when
    # the v1 lane is invoked.
    "domain.translators",
}


def _check_classified_promoted_imports(path: Path) -> list[str]:
    """Return module-level violations for a single PROMOTED_CORE file.

    Any import from a CLASSIFIED_FORBIDDEN_MODULES module is a HARD
    failure — there is no allowlist for this scan. Imports that live
    inside function bodies (lazy imports) are not seen by this AST
    walk, by design: the promoted dispatcher's legacy fallback uses
    function-local imports so the module never depends on the legacy
    surface at load time.
    """
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
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if any(
                    mod == bad or mod.startswith(bad + ".")
                    for bad in CLASSIFIED_FORBIDDEN_MODULES
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: forbidden `import {mod}` — "
                        "PROMOTED_CORE files must not depend on legacy "
                        "Indian primitives. See ADR 0016."
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(
                mod == bad or mod.startswith(bad + ".")
                for bad in CLASSIFIED_FORBIDDEN_MODULES
            ):
                violations.append(
                    f"{rel}:{node.lineno}: forbidden `from {mod} import …` "
                    "— PROMOTED_CORE files must not depend on legacy "
                    "Indian primitives. See ADR 0016."
                )
    return violations


def test_classified_promoted_files_have_no_forbidden_imports() -> None:
    """ADR 0016 — classified PROMOTED_CORE files cannot import legacy
    Indian primitives at module-load time. The named compatibility
    shims (e.g. ``domain/translators.py``) live in COMPATIBILITY_SHIM
    and are exempt by classification.
    """
    files = _read_classified_promoted_core()
    assert files, (
        "PROMOTED_CORE list missing — run "
        "`uv run python scripts/audit/classify_files.py`."
    )
    violations: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        violations.extend(_check_classified_promoted_imports(path))
    assert not violations, (
        "PROMOTED_CORE import contract violated:\n  "
        + "\n  ".join(violations)
    )


def _string_constants_in_module(tree: ast.Module) -> Iterable[tuple[str, int]]:
    """Yield (string_value, lineno) for every `ast.Constant` whose value
    is a ``str``, *excluding* docstrings, module/class/function-level
    docstring positions, and enum-value assignments where the target
    name equals the string value (the ``INR = "INR"`` pattern).
    """
    skipped_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                skipped_ids.add(id(body[0].value))
        # Enum-value pattern: `NAME = "NAME"` inside any class body.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == node.value.value
            ):
                skipped_ids.add(id(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skipped_ids:
                continue
            yield node.value, getattr(node, "lineno", 0)


def _docstring_line_numbers(tree: ast.Module) -> set[int]:
    """Return the set of line numbers occupied by module/class/function
    docstrings — used by the regex pass to skip them.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                start = first.lineno
                end = getattr(first, "end_lineno", start) or start
                for ln in range(start, end + 1):
                    lines.add(ln)
    return lines


def _enum_self_assign_lines(tree: ast.Module) -> set[int]:
    """Return line numbers of ``NAME = "NAME"`` assignments — the
    enum-member self-assignment pattern. Skipped by the regex pass.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.targets[0].id == node.value.value
        ):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            for ln in range(start, end + 1):
                lines.add(ln)
    return lines


def _literal_violations_in_file(
    path: Path, allowlist: dict[str, set[str]] | None = None
) -> list[str]:
    """Return per-line literal violations for one file."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    if allowlist is None:
        allowlist = LITERAL_ALLOWLIST
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel}: could not read: {exc}"]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: syntax error: {exc}"]

    violations: list[str] = []

    # AST pass — string constants only (no docstrings, no enum-value
    # ``NAME = "NAME"`` self-assignments).
    for value, lineno in _string_constants_in_module(tree):
        for literal in INDIA_LITERALS:
            if rel in allowlist.get(literal, set()):
                continue
            if _literal_pattern(literal).search(value):
                violations.append(
                    f"{rel}:{lineno}: India-specific literal {literal!r} "
                    f"in string constant {value!r} — promoted/scanned paths "
                    "must use venue/region metadata. See ADR 0006."
                )

    # Regex pass — strip comments line-by-line, skip docstring spans,
    # then scan the remaining source for the literals to catch any
    # non-AST cases (f-strings' joined parts, raw template strings
    # missed by Constant walk, etc.).
    docstring_lines = _docstring_line_numbers(tree)
    enum_self_lines = _enum_self_assign_lines(tree)
    for line_no, raw in enumerate(source.splitlines(), start=1):
        if line_no in docstring_lines or line_no in enum_self_lines:
            continue
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        for literal in INDIA_LITERALS:
            if rel in allowlist.get(literal, set()):
                continue
            if _literal_pattern(literal).search(line):
                # de-dupe with AST hits on the same line/literal pair
                msg_tag = f"{rel}:{line_no}:"
                literal_repr = repr(literal)
                already = any(
                    v.startswith(msg_tag) and literal_repr in v for v in violations
                )
                if already:
                    continue
                violations.append(
                    f"{rel}:{line_no}: India-specific literal {literal!r} "
                    f"in source line — promoted/scanned paths must use "
                    "venue/region metadata. See ADR 0006."
                )
    return violations


def test_no_india_specific_literals_in_promoted_paths() -> None:
    """ADR 0006 — promoted paths must not embed India-specific literals."""
    files = _discover_promoted_python_files()
    assert files, "expected at least one promoted .py file"
    violations: list[str] = []
    for path in files:
        violations.extend(_literal_violations_in_file(path))
    assert not violations, (
        "Promoted-lane literal contract violated:\n  "
        + "\n  ".join(violations)
    )


def _read_classified_promoted_core() -> list[Path]:
    """Read PROMOTED_CORE entries from the file-classification report."""
    report = REPO_ROOT / "docs" / "refactor" / "file_classification.md"
    if not report.is_file():
        return []
    text = report.read_text(encoding="utf-8")
    files: list[Path] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            in_section = head.startswith("PROMOTED_CORE")
            continue
        if in_section and line.startswith("- `") and line.endswith("`"):
            rel = line[3:-1]
            files.append(REPO_ROOT / rel)
    return files


def test_no_india_literals_in_classified_promoted_files() -> None:
    """ADR 0016 — every file the classifier marks PROMOTED_CORE must
    pass the India-literal scan.

    The classification (Phase 0) is the contract; this test is the
    runtime gate. If a PROMOTED_CORE file picks up an India literal,
    either the file changes home (rules YAML) or the literal goes.
    """
    files = _read_classified_promoted_core()
    assert files, (
        "PROMOTED_CORE list missing or empty — run "
        "`uv run python scripts/audit/classify_files.py` to regenerate "
        "docs/refactor/file_classification.md."
    )
    violations: list[str] = []
    for path in files:
        if not path.is_file():
            violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: classified PROMOTED_CORE but not on disk")
            continue
        violations.extend(_literal_violations_in_file(path))
    assert not violations, (
        "Classified-PROMOTED_CORE literal contract violated:\n  "
        + "\n  ".join(violations)
    )


# Files in services/, domain/, utils/ that are pre-existing legacy or
# Indian-specific surfaces. Excluded from the warning scan in this
# phase; later phases will narrow the list.
_WARNING_SCAN_EXCLUDES: frozenset[str] = frozenset(
    {
        "services/quotes_service.py",
        "services/history_service.py",
        "services/place_order_service.py",
        "services/expiry_service.py",
        "services/flow_executor_service.py",
        "utils/constants.py",
        "utils/auth_utils.py",
        "utils/session.py",
    }
)

_WARNING_SCAN_GLOB_EXCLUDES: tuple[str, ...] = (
    "services/option_*.py",
    "services/options_*.py",
)


def _discover_warning_scan_files() -> list[Path]:
    """Walk services/, domain/, utils/ and yield files NOT in the
    pre-existing-legacy exclusion list."""
    import fnmatch

    roots = ("services", "domain", "utils")
    files: list[Path] = []
    for root in roots:
        d = REPO_ROOT / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel in _WARNING_SCAN_EXCLUDES:
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in _WARNING_SCAN_GLOB_EXCLUDES):
                continue
            files.append(p)
    return files


def test_warning_scan_for_india_literals_in_core_modules(
    request: pytest.FixtureRequest,
) -> None:
    """Phase 1 warning-only scan over services/, domain/, utils/.

    This is **not** a hard failure — it prints any literal hits so the
    operator can see what the later phases will need to fix. Becomes a
    hard failure on a per-file basis once each owning phase has cleared
    the file (Phases 4-6 narrow the exclusion list).
    """
    files = _discover_warning_scan_files()
    findings: list[str] = []
    for path in files:
        findings.extend(_literal_violations_in_file(path, allowlist={}))
    if findings:
        # Print for visibility but do not fail.
        print("\n[lane-isolation warning] India-literal hits in core modules:")
        for line in findings[:50]:
            print(f"  {line}")
        if len(findings) > 50:
            print(f"  ... and {len(findings) - 50} more")
        request.config.cache.set(
            "lane_isolation/warning_count", len(findings)
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


def test_literal_allowlist_entries_reference_existing_files() -> None:
    """Same hygiene check for the LITERAL_ALLOWLIST."""
    for literal, paths in LITERAL_ALLOWLIST.items():
        for rel in paths:
            abs_path = REPO_ROOT / rel
            assert abs_path.is_file(), (
                f"LITERAL_ALLOWLIST entry {literal!r} -> {rel!r} points "
                "to a file that no longer exists; remove the entry."
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
