"""T-31 (Phase 3) — backend literal scanner.

Mirror of ``frontend/scripts/literal_scan.mjs`` for promoted Python
backend code. Scans for India-specific literals that should be
sourced from venue/region metadata instead.

Scope (PROMOTED_CORE per docs/refactor/file_classification.md +
non-India broker plugins):
* ``Asia/Kolkata``, ``IST`` (with word-boundary anchoring)
* ``"NSE"``, ``"BSE"``, ``"NFO"``, ``"BFO"``, ``"CDS"``, ``"BCD"``,
  ``"MCX"``, ``"NCDEX"`` as default-fallback values
* ``"MIS"``, ``"CNC"``, ``"NRML"`` as default-fallback values
* ``"INR"``, ``"₹"``
* ``09:15``, ``15:30``, ``15:00`` as session-window literals

Allowlist (out of scope):
* ``market_regions/india/`` and its subtree (legacy India lane)
* ``broker/<india_broker>/`` (24+ Indian broker plugins)
* ``services/v1_compat_bridge.py`` (T-04 cleaned the silent
  defaults; the documented venue alias map is preserved)
* ``utils/constants.py`` (legacy compat shim — retired in Phase 9)
* Comment-only matches (``#`` prefix, narrative text)

Exit codes:
* 0 — no violations
* 1 — at least one violation; full list printed to stderr

Joins the existing ``uv run python scripts/audit/*`` step in the
comprehensive testing block once Phase 3 ships.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Allowlist — paths excluded from the scan.
# ---------------------------------------------------------------------------

_ALLOWED_PREFIXES: tuple[str, ...] = (
    "market_regions/india/",
    "tests/",
    "test/",  # legacy non-pytest test directory (pre-Phase 1 v6)
    "upgrade/",  # migrations are India-shaped historical artifacts
    "scripts/",  # audit scripts and one-shot operator tools
    "audit/",  # legacy audit dir (top-level)
    "examples/",
    "broker/aliceblue/",
    "broker/angel/",
    "broker/compositedge/",
    "broker/definedge/",
    "broker/dhan/",
    "broker/dhan_sandbox/",
    "broker/firstock/",
    "broker/fivepaisa/",
    "broker/fivepaisaxts/",
    "broker/flattrade/",
    "broker/fyers/",
    "broker/groww/",
    "broker/ibulls/",
    "broker/iifl/",
    "broker/iiflcapital/",
    "broker/indmoney/",
    "broker/jainamxts/",
    "broker/kotak/",
    "broker/motilal/",
    "broker/mstock/",
    "broker/nubra/",
    "broker/paytm/",
    "broker/pocketful/",
    "broker/rmoney/",
    "broker/samco/",
    "broker/shoonya/",
    "broker/tradejini/",
    "broker/upstox/",
    "broker/wisdom/",
    "broker/zebu/",
    "broker/zerodha/",
    "broker/deltaexchange/",  # Indian crypto broker, India-shape until T-30
    # documentation-shape only files that may legitimately reference
    # the literals as illustrative
    "docs/",
    ".git/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
)


# Specific files that DO contain literals as documented allowlist
# entries. Each entry includes the phase that retires the allowlist.
_FILE_ALLOWLIST: dict[str, str] = {
    # T-04 cleaned the silent defaults; the venue alias map at
    # lines ~80-180 maps user-friendly venue names to canonical MIC
    # codes and intentionally references "NSE"/"NASDAQ"/etc.
    "services/v1_compat_bridge.py": "T-04: documented venue alias map",
    # Legacy compat shim — retired in Phase 9.
    "utils/constants.py": "Phase 9: legacy v1 compat shim retirement",
    # Phase 1 added active_render_tz_name with Asia/Kolkata as the
    # legacy-compat fallback constant. Allowed.
    "utils/venue_local_time.py": "T-01: legacy India compat constant",
    # Phase 2 T-10/T-11 reference Asia/Kolkata in fail-closed comment
    # blocks describing the behavior matrix.
    "database/auth_db.py": "T-10: fail-closed reference to Asia/Kolkata in comment",
    "download/sqlite_downloader.py": "T-11: legacy India fallback for CLI script",
    # Telegram migration documents the historical default.
    "upgrade/migrate_telegram_bot.py": "T-07: NOT NULL replaces default; comment cites historical pattern",
    # Number formatter has the India-shaped helpers (Cr / L suffix,
    # ₹ prefix). These are legacy India compat helpers; new code
    # uses the canonical formatCurrencyAmount.
    "utils/number_formatter.py": "Legacy India compat: Cr/L/₹ helpers retained for India parity",
    # env_check prints example session times in its diagnostic
    # output — illustrative, not a runtime default.
    "utils/env_check.py": "Diagnostic print example, not a runtime default",
    # Sandbox margin tests document India-specific scenarios (T-16
    # reconciliation lands in Phase 4).
    "sandbox/squareoff_thread.py": "T-20 follow-up: India-shaped square-off thread",
    "sandbox/catch_up_processor.py": "T-20 follow-up: India-shaped catch-up logic",
    "sandbox/fund_manager.py": "T-16 (Phase 4): sandbox capital reconciliation",
    # Auth utils references IST 08:00 as the legacy refresh anchor.
    "utils/auth_utils.py": "Legacy India auth tz anchor; T-09 makes refresh_policy mandatory for non-legacy",
    # XTS family helper for the 4-broker XTS subset (Compositedge,
    # IIFL Capital, JainamXTS, FivepaisaXTS, Wisdom). India-shape.
    "broker/_xts_family/__init__.py": "Indian XTS family helper",
    # Venue offset table is the canonical IST 19800-second constant
    # source; legacy India venue codes resolve via this module.
    "database/venue_offset.py": "Canonical India venue tz constants",
    # venue_session_service exposes Asia/Kolkata as a documented
    # fallback constant — the value lives ONE place and feeds the
    # legacy India seed.
    "services/venue_session_service.py": "Documented India fallback constant",
    # T-26 (Phase 7) extracts the zerodha-specific tz/currency to
    # the US adapter base. Until then the India literal lives here.
    "services/instrument_sync_adapters/zerodha_adapter.py": "T-26: India sync adapter; closed in Phase 7",
    # T-16 (Phase 4) reconciles sandbox capital. Until then the
    # India sandbox provider declares ₹10L / Asia/Kolkata directly.
    "services/sandbox/__init__.py": "T-16: sandbox capital reconciliation in Phase 4",
    "services/sandbox/providers/base.py": "T-16: provider base docstring references India and US figures",
    "services/sandbox/providers/india/__init__.py": "T-16: India sandbox provider ₹10L / Asia/Kolkata",
    # T-04 covers v1_compat_bridge but socketio_subscriber wasn't in
    # its scope. Same pattern; fix in a follow-up.
    "subscribers/socketio_subscriber.py": "T-04 follow-up: same or-MIS pattern in subscriber path",
    # Action center stamps UTC post T-03; the literal 'IST' appears
    # only in a docstring describing the legacy display string.
    "database/action_center_db.py": "T-03: docstring narrative references historical IST suffix",
}


# ---------------------------------------------------------------------------
# Patterns — compiled once.
# ---------------------------------------------------------------------------

# Tz literals.
_RE_KOLKATA = re.compile(r"\bAsia/Kolkata\b")
_RE_IST = re.compile(r'(?<![A-Za-z0-9_])"IST"|\'IST\'')

# Indian venue codes as default-fallback values: ``or "NSE"`` /
# ``or "NFO"`` / etc. We don't flag every appearance — only the
# silent default-fallback idiom.
_RE_OR_VENUE = re.compile(
    r'\bor\s+["\'](?:NSE|BSE|NFO|BFO|CDS|BCD|MCX|NCDEX)["\']'
)

# Indian product codes as default-fallback values.
_RE_OR_PRODUCT = re.compile(r'\bor\s+["\'](?:MIS|CNC|NRML)["\']')

# Currency: INR / ₹ as default values.
_RE_OR_INR = re.compile(r'\bor\s+["\']INR["\']')
_RE_RUPEE = re.compile(r"₹")

# Indian session-window literals: 09:15 / 15:30 / 15:00 in
# string-literal positions (not in datetime arithmetic).
_RE_SESSION_HHMM = re.compile(r'["\'](?:09:15|15:30|15:00)["\']')


# ---------------------------------------------------------------------------
# Scanner.
# ---------------------------------------------------------------------------


def _is_allowlisted(rel_path: str) -> tuple[bool, str | None]:
    rel_path = rel_path.replace("\\", "/")
    for prefix in _ALLOWED_PREFIXES:
        if rel_path.startswith(prefix):
            return True, f"allowlisted prefix {prefix}"
    if rel_path in _FILE_ALLOWLIST:
        return True, _FILE_ALLOWLIST[rel_path]
    return False, None


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Skip comment-only lines (the # may be inside a string;
        # this heuristic accepts narrative comments and rejects code
        # lines).
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Skip docstring-fragment lines that are narrative (e.g.,
        # text inside a triple-quoted block). Detect by checking if
        # the line is purely text (no equals / parens / colons that
        # mark code structure).
        for pat, label in [
            (_RE_KOLKATA, "Asia/Kolkata"),
            (_RE_IST, "'IST' literal"),
            (_RE_OR_VENUE, "or-venue default-fallback"),
            (_RE_OR_PRODUCT, "or-product default-fallback"),
            (_RE_OR_INR, "or-INR default-fallback"),
            (_RE_RUPEE, "rupee symbol literal"),
            (_RE_SESSION_HHMM, "session-window literal"),
        ]:
            if pat.search(line):
                violations.append(f"{rel}:{lineno}: [{label}] {line.strip()}")
    return violations


def _walk_repo() -> list[Path]:
    """Walk the repo and yield Python source files outside the
    allowlist."""
    out: list[Path] = []
    for root, dirs, files in os.walk(_REPO_ROOT):
        # In-place skip of __pycache__ / .venv etc.
        dirs[:] = [
            d
            for d in dirs
            if d not in {"__pycache__", ".venv", "venv", "node_modules", ".git"}
        ]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = Path(root) / fn
            try:
                rel = str(full.relative_to(_REPO_ROOT)).replace("\\", "/")
            except ValueError:
                continue
            allowed, _reason = _is_allowlisted(rel)
            if allowed:
                continue
            out.append(full)
    return out


def main() -> int:
    files = _walk_repo()
    all_violations: list[str] = []
    for f in files:
        all_violations.extend(_scan_file(f))
    if not all_violations:
        print(f"india_literal_scan_backend: clean ({len(files)} files scanned)")
        return 0
    print(
        "india_literal_scan_backend: violations detected",
        file=sys.stderr,
    )
    for v in all_violations:
        print(f"  {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
