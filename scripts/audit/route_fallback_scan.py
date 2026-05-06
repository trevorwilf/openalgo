"""Walk every route blueprint/namespace under restx_api/* and emit a
Markdown table at docs/refactor/route_fallback_inventory.md.

For each route module we report:

* the route path (taken from `add_namespace(..., path=...)` for v1, or
  the v2 builder for v2)
* the HTTP method(s) implemented by Resource subclasses
* lane disposition (legacy / promoted / dual)
* whether the promoted dispatch fails closed for non-India brokers
* which legacy services the module imports (the leak surface)
* whether a capability check is performed
* whether instrument resolution uses the canonical resolver
* the v3 phase that owns closing the open behavior

The goal is operator-readable, not perfect AST-aware. The table is the
single source of truth that ``tests/contracts/test_route_fallback_inventory.py``
parses to assert every promoted route is either fail-closed or has a
phase that closes it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_INIT = REPO_ROOT / "restx_api" / "__init__.py"
V2_INIT = REPO_ROOT / "restx_api" / "v2" / "__init__.py"
REPORT = REPO_ROOT / "docs" / "refactor" / "route_fallback_inventory.md"


LEGACY_SERVICE_CALLS: dict[str, str] = {
    # service module     -> short label rendered in table
    "services.quotes_service": "quotes_service",
    "services.history_service": "history_service",
    "services.place_order_service": "place_order_service",
    "services.basket_order_service": "basket_order_service",
    "services.split_order_service": "split_order_service",
    "services.margin_service": "margin_service",
    "services.place_smart_order_service": "place_smart_order_service",
    "services.place_options_order_service": "place_options_order_service",
    "services.options_multiorder_service": "options_multiorder_service",
    "services.expiry_service": "expiry_service",
    "services.option_chain_service": "option_chain_service",
    "services.option_greeks_service": "option_greeks_service",
    "services.option_symbol_service": "option_symbol_service",
    "services.iv_chart_service": "iv_chart_service",
    "services.gex_service": "gex_service",
    "services.synthetic_future_service": "synthetic_future_service",
    "services.straddle_chart_service": "straddle_chart_service",
    "services.vol_surface_service": "vol_surface_service",
    "services.flow_executor_service": "flow_executor_service",
    "services.symbol_service": "symbol_service",
    "services.search_service": "search_service",
    "services.depth_service": "depth_service",
    "services.cancel_order_service": "cancel_order_service",
    "services.cancel_all_order_service": "cancel_all_order_service",
    "services.modify_order_service": "modify_order_service",
    "services.close_position_service": "close_position_service",
    "services.orderbook_service": "orderbook_service",
    "services.orderstatus_service": "orderstatus_service",
    "services.openposition_service": "openposition_service",
    "services.positionbook_service": "positionbook_service",
    "services.holdings_service": "holdings_service",
    "services.funds_service": "funds_service",
    "services.tradebook_service": "tradebook_service",
    "services.historify_service": "historify_service",
    "services.chart_service": "chart_service",
    "services.intervals_service": "intervals_service",
    "services.market_calendar_service": "market_calendar_service",
    "services.instruments_service": "instruments_service",
    "services.analyzer_service": "analyzer_service",
    "services.sandbox_service": "sandbox_service",
    "services.telegram_alert_service": "telegram_alert_service",
    "services.ping_service": "ping_service",
}

LEGACY_DB_IMPORTS: dict[str, str] = {
    "utils.constants": "utils.constants",
    "database.token_db": "database.token_db",
    "database.token_db_enhanced": "database.token_db_enhanced",
    "database.symbol": "database.symbol",
    "database.market_calendar_db": "database.market_calendar_db",
}

CANONICAL_RESOLVER_HINTS: tuple[str, ...] = (
    "services.instrument_resolution",
    "database.instruments_repo",
    "instruments_get_by_id",
    "resolve_instrument",
)

CAPABILITY_HINTS: tuple[str, ...] = (
    "_capability_precheck",
    "supported_order_types",
    "supported_time_in_force",
    "_broker_lane_check",
    "promoted_lane_required_for_non_india_broker",
    "translator_not_registered",
    "quote_adapter_not_registered",
    "bar_adapter_not_registered",
    "is_feature_enabled_for_active_region",
)

FAILCLOSED_HINTS: tuple[str, ...] = (
    "promoted_lane_required_for_non_india_broker",
    "translator_not_registered",
    "quote_adapter_not_registered",
    "bar_adapter_not_registered",
    "promoted_capability_unavailable",
)


@dataclass
class RouteEntry:
    module: Path
    namespace_name: str = ""
    namespace_path: str = ""
    methods: list[str] = field(default_factory=list)
    lane: str = "legacy"  # legacy / promoted / dual
    legacy_calls: list[str] = field(default_factory=list)
    legacy_imports: list[str] = field(default_factory=list)
    capability_check: bool = False
    instrument_resolution: str = "none"  # canonical / legacy_token / none
    fail_closed_for_non_india: str = "n/a"  # yes / no / n/a
    owning_phase: str = "none"

    @property
    def rel(self) -> str:
        return self.module.relative_to(REPO_ROOT).as_posix()


def _parse_v1_namespace_paths() -> dict[str, str]:
    """Map module name -> URL path from `restx_api/__init__.py`.

    Handles both legacy relative imports (``from .module import``) and
    the absolute-path form used after the Phase 9-bis-physical
    relocation of v1 internals to
    ``market_regions/india/legacy_v1/restx_api/``.
    """
    text = V1_INIT.read_text(encoding="utf-8")
    ns_alias_to_module: dict[str, str] = {}
    # Pattern A — legacy relative form: ``from .module import api as alias``
    rel_pat = re.compile(
        r"\s*from\s+\.([\w_]+)\s+import\s+api\s+as\s+([\w_]+)\s*$"
    )
    # Pattern B — absolute form after physical relocation:
    # ``from market_regions.india.legacy_v1.restx_api.module import api as alias``
    abs_pat = re.compile(
        r"\s*from\s+market_regions\.india\.legacy_v1\.restx_api\.([\w_]+)"
        r"\s+import\s+api\s+as\s+([\w_]+)\s*$"
    )
    for line in text.splitlines():
        m = rel_pat.match(line) or abs_pat.match(line)
        if m:
            module, alias = m.group(1), m.group(2)
            ns_alias_to_module[alias] = module

    alias_to_path: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(
            r"\s*api\.add_namespace\(([\w_]+),\s*path=\"([^\"]+)\"\)", line
        )
        if m:
            alias, path = m.group(1), m.group(2)
            alias_to_path[alias] = path

    return {
        ns_alias_to_module[a]: p
        for a, p in alias_to_path.items()
        if a in ns_alias_to_module
    }


def _parse_v2_namespace_paths() -> dict[str, str]:
    """Map module file stem -> URL path from `restx_api/v2/__init__.py`."""
    text = V2_INIT.read_text(encoding="utf-8")
    alias_to_module: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(
            r"\s*from\s+restx_api\.v2\.([\w_]+)\s+import\s+(?:api\s+as\s+)?([\w_]+)",
            line.strip(),
        )
        if m:
            module, alias = m.group(1), m.group(2)
            alias_to_module[alias] = module

    module_to_path: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(
            r"\s*api\.add_namespace\(([\w_]+),\s*path=\"([^\"]+)\"\)", line
        )
        if m:
            alias, path = m.group(1), m.group(2)
            mod = alias_to_module.get(alias, alias.replace("_ns", "").replace("_api", ""))
            module_to_path[mod] = path

    return module_to_path


def _resource_methods(tree: ast.Module) -> list[str]:
    methods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = (
                    base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                )
                if base_name in {"Resource", "MethodView"}:
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if child.name.lower() in {"get", "post", "put", "patch", "delete"}:
                                methods.add(child.name.upper())
    return sorted(methods)


def _scan_module(path: Path, ns_path: str, version: str) -> RouteEntry:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    entry = RouteEntry(module=path, namespace_path=ns_path)

    # Namespace name
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "api"
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", "") == "Namespace"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
        ):
            entry.namespace_name = str(node.value.args[0].value)
            break

    entry.methods = _resource_methods(tree)

    # Imports + names appearing in the source
    legacy_calls: set[str] = set()
    legacy_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (
                node.module
                if isinstance(node, ast.ImportFrom)
                else (node.names[0].name if node.names else "")
            )
            if mod is None:
                continue
            for legacy_mod, label in LEGACY_SERVICE_CALLS.items():
                if mod == legacy_mod or mod.startswith(legacy_mod + "."):
                    legacy_calls.add(label)
            for legacy_mod, label in LEGACY_DB_IMPORTS.items():
                if mod == legacy_mod or mod.startswith(legacy_mod + "."):
                    legacy_imports.add(label)

    entry.legacy_calls = sorted(legacy_calls)
    entry.legacy_imports = sorted(legacy_imports)

    # Capability check / fail-closed / canonical resolver hints
    src_lower = text
    entry.capability_check = any(h in src_lower for h in CAPABILITY_HINTS)
    # Metadata-only routes do not auth a broker session (no
    # resolve_auth) so the fail-closed concept doesn't apply.
    is_broker_dispatch = "resolve_auth" in src_lower
    if version == "v2":
        if not is_broker_dispatch:
            entry.fail_closed_for_non_india = "n/a"
        elif any(h in src_lower for h in FAILCLOSED_HINTS):
            entry.fail_closed_for_non_india = "yes"
        else:
            entry.fail_closed_for_non_india = "no"
    if any(h in src_lower for h in CANONICAL_RESOLVER_HINTS):
        entry.instrument_resolution = "canonical"
    elif any(
        legacy_token in src_lower
        for legacy_token in (
            "from database.token_db",
            "from database.symbol",
            "from database.token_db_enhanced",
        )
    ):
        entry.instrument_resolution = "legacy_token"
    else:
        entry.instrument_resolution = "none"

    # Lane disposition
    if version == "v2":
        if entry.legacy_calls:
            entry.lane = "dual"  # promoted with legacy fallback
        else:
            entry.lane = "promoted"
    else:
        entry.lane = "legacy"

    # Owning phase mapping (v3 phases that close known leaks). When
    # fail_closed_non_india=yes the route is already safe for non-India
    # brokers; the legacy fallback is reserved for India/crypto and is
    # the expected design, not an open leak.
    if version == "v2":
        if entry.fail_closed_for_non_india in {"yes", "n/a"}:
            entry.owning_phase = "none"
        elif "quotes_service" in entry.legacy_calls:
            entry.owning_phase = "phase 2"
        elif "history_service" in entry.legacy_calls:
            entry.owning_phase = "phase 2"
        elif entry.fail_closed_for_non_india == "no":
            entry.owning_phase = "phase 2"
        else:
            entry.owning_phase = "none"
    else:
        # Legacy v1 routes are intentionally legacy. They are owned by
        # later phases only when they have non-India consumers.
        entry.owning_phase = "none"

    return entry


def _gather_entries() -> list[RouteEntry]:
    v1_paths = _parse_v1_namespace_paths()
    v2_paths = _parse_v2_namespace_paths()

    entries: list[RouteEntry] = []
    # v1 modules can live in two places after the Phase 9-bis-physical
    # relocation: the original ``restx_api/`` (re-export shims) or the
    # canonical ``market_regions/india/legacy_v1/restx_api/`` (real code).
    v1_search_dirs = [
        REPO_ROOT / "restx_api",
        REPO_ROOT / "market_regions" / "india" / "legacy_v1" / "restx_api",
    ]
    for module_stem, ns_path in v1_paths.items():
        path = next(
            (d / f"{module_stem}.py" for d in v1_search_dirs
             if (d / f"{module_stem}.py").is_file()),
            None,
        )
        if path is None:
            continue
        entries.append(_scan_module(path, f"/api/v1{ns_path}", version="v1"))

    for module_stem, ns_path in v2_paths.items():
        path = REPO_ROOT / "restx_api" / "v2" / f"{module_stem}.py"
        if not path.is_file():
            continue
        entries.append(_scan_module(path, f"/api/v2{ns_path}", version="v2"))

    return entries


def render_markdown(entries: Iterable[RouteEntry]) -> str:
    lines = [
        "# Route fallback inventory — market-agnostic v3",
        "",
        "Generated by `scripts/audit/route_fallback_scan.py`. The table",
        "covers every namespace registered in",
        "`restx_api/__init__.py` and `restx_api/v2/__init__.py`. The",
        "`owning_phase_to_fix` column points at the v3 phase whose",
        "scope closes the open behavior (legacy fallback, missing",
        "capability check, etc.).",
        "",
        "Lane semantics:",
        "",
        "* `legacy` — v1 namespaces. Frozen, India parity guaranteed.",
        "* `promoted` — v2 namespaces with no legacy fallback path.",
        "* `dual` — v2 namespaces that still fall back to a legacy",
        "  service when the promoted adapter/translator is missing.",
        "",
        "| route_path | method | lane | fail_closed_non_india | legacy_fallback_calls | capability_check | instrument_resolution | owning_phase_to_fix |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def _fmt_methods(methods: list[str]) -> str:
        return ",".join(methods) if methods else "—"

    def _fmt_list(values: list[str]) -> str:
        return ", ".join(values) if values else "—"

    for entry in sorted(entries, key=lambda e: e.namespace_path):
        lines.append(
            "| `{path}` | {methods} | {lane} | {fc} | {fb} | {cap} | {ir} | {phase} |".format(
                path=entry.namespace_path,
                methods=_fmt_methods(entry.methods),
                lane=entry.lane,
                fc=entry.fail_closed_for_non_india,
                fb=_fmt_list(entry.legacy_calls or entry.legacy_imports),
                cap="yes" if entry.capability_check else "no",
                ir=entry.instrument_resolution,
                phase=entry.owning_phase,
            )
        )

    lines.append("")
    lines.append("## Source modules")
    lines.append("")
    for entry in sorted(entries, key=lambda e: e.rel):
        lines.append(
            f"- `{entry.namespace_path}` — `{entry.rel}` (Namespace: `{entry.namespace_name}`)"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    entries = _gather_entries()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_markdown(entries), encoding="utf-8")
    print(f"Wrote {REPORT.relative_to(REPO_ROOT)} ({len(entries)} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
