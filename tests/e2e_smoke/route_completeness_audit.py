"""Audit every v1 namespace and check whether a v2 counterpart exists.

Reads ``restx_api/__init__.py`` for the v1 namespace list, derives a
candidate v2 path per ADR/migration-doc conventions, and probes the
running Flask. Reports:

* MISSING — v2 returns the SPA index.html shell (route doesn't exist).
* OK      — v2 returns JSON with ``data`` key.
* ROUTED  — v2 returns JSON ``error`` (route exists but call failed,
            usually auth or broker-state related).
* UNKNOWN — couldn't classify.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
API_KEY = (ROOT / "tests" / "e2e_smoke" / "_artifacts" / "api_key.txt").read_text().strip()
BASE = "http://127.0.0.1:5000"

# v1 namespace path -> candidate v2 path. Conventions:
# - kebab-case path stays the same on v2
# - some renames per migration doc
V1_TO_V2_OVERRIDES = {
    "/placeorder":      "/orders",
    "/modifyorder":     "/orders/<id>/modify",  # has order id, can't probe blind
    "/cancelorder":     "/orders/<id>/cancel",
    "/cancelallorder":  "/orders/cancelall",
    "/closeposition":   "/orders/closeposition",
    "/quotes":          "/quotes",
    "/multiquotes":     "/quotes",
    "/history":         "/bars",
    "/depth":           "/depth",
    "/funds":           "/balances",
    "/orderbook":       "/orders",
    "/tradebook":       "/trades",
    "/positionbook":    "/positions",
    "/holdings":        "/holdings",
    "/optionchain":     "/options/chain",
    "/optiongreeks":    "/options/greeks",
    "/optionsorder":    "/orders/options",
    "/symbol":          "/instruments/<id>",
    "/expiry":          "/options/expiries",
    "/intervals":       "/bars/intervals",
    "/instruments":     "/instruments",
    "/market/holidays": "/calendar/holidays",
    "/market/timings":  "/calendar/timings",
    "/ping":            "/ping",
    "/openposition":    "/positions/<symbol>",
    "/optionsymbol":    "/options/symbol",
    "/multioptiongreeks": "/options/greeks",
    "/syntheticfuture": "/options/synthetic-future",
    "/orderstatus":     "/orders/<id>",
    "/ticker":          "/quotes",
    "/search":          "/instruments/search",
    "/basketorder":     "/orders/basket",
    "/splitorder":      "/orders/split",
    "/placesmartorder": "/orders/placesmart",
    "/options/multiorder": "/orders/options/multi",
    "/optionsmultiorder":  "/orders/options/multi",
    "/analyzer":        "/analyzer",
    "/telegram":        "/telegram",
    "/margin":          "/margin",
    "/chart":           "/chart",
    "/pnl":             "/pnl",
}


def parse_v1_namespaces() -> list[str]:
    init = ROOT / "restx_api" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    paths = []
    for line in text.splitlines():
        m = re.match(
            r"^api\.add_namespace\([\w_]+,\s*path=\"(/[^\"]+)\"\)", line.strip(),
        )
        if m:
            paths.append(m.group(1))
    return paths


def classify(path: str) -> tuple[str, int, str]:
    """Probe ``path`` (already-resolved to a v2 URL) and return
    ``(verdict, status_code, body_preview)``."""
    if "<" in path:
        return "skip-needs-id", 0, ""
    url = f"{BASE}/api/v2{path}?apikey={API_KEY}"
    try:
        r = httpx.get(url, timeout=5.0)
    except Exception as e:
        return "exception", 0, str(e)[:80]
    body = r.text[:200]
    if "doctype" in body.lower():
        return "MISSING", r.status_code, "(spa shell)"
    try:
        j = r.json()
    except Exception:
        return "UNKNOWN", r.status_code, body[:100]
    if isinstance(j, dict) and "data" in j:
        return "OK", r.status_code, json.dumps(j["data"], default=str)[:100]
    if isinstance(j, dict) and "error" in j:
        code = j["error"].get("code", "?")
        return "ROUTED", r.status_code, f"error code={code}"
    return "UNKNOWN", r.status_code, body[:100]


def main() -> int:
    v1_paths = parse_v1_namespaces()
    print(f"=== v1 has {len(v1_paths)} namespaces ===\n")

    missing = []
    for v1 in v1_paths:
        v2 = V1_TO_V2_OVERRIDES.get(v1, v1)  # default: keep same path
        verdict, status, preview = classify(v2)
        ind = {"OK": "+", "MISSING": "-", "ROUTED": "*",
                "skip-needs-id": "?", "UNKNOWN": "?",
                "exception": "!"}.get(verdict, "?")
        print(f"  {ind} v1 {v1:25s} -> v2 {v2:30s} {verdict:15s} "
              f"http={status} {preview[:80]}")
        if verdict == "MISSING":
            missing.append((v1, v2))

    print(f"\n=== summary: {len(missing)} missing v2 routes ===")
    for v1, v2 in missing:
        print(f"  v1 {v1} → v2 {v2}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
