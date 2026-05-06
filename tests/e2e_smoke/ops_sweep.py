"""Operator-dashboard API sweep — health / latency / traffic / security.

These dashboards run on session-cookie auth (not /api/v2 apikey) so we
read the Playwright-captured session cookie and walk every documented
GET endpoint. Read-only — never POSTs to the ban/unban/clear-404 mutators.
"""
from __future__ import annotations

import json
import sys
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "tests" / "e2e_smoke" / "_artifacts"
COOKIES = ART / "cookies.txt"
BASE = "http://127.0.0.1:5000"

# Playwright netscape jar isn't accepted by curl/httpx cleanly on
# Windows due to a path field quirk; load directly from storage.json.
storage = json.loads((ART / "storage.json").read_text())
SESSION = next((c["value"] for c in storage["cookies"] if c["name"] == "session"), None)
if not SESSION:
    print("missing session cookie")
    sys.exit(2)
cookies = {"session": SESSION}

results = []

def call(c, method, path, *, expect=(200,), params=None, json_body=None):
    started = time.perf_counter()
    try:
        r = c.request(method, f"{BASE}{path}",
                       params=params, json=json_body, timeout=15.0,
                       follow_redirects=False)
        elapsed = round((time.perf_counter() - started) * 1000)
        body_preview = ""
        try:
            body_preview = json.dumps(r.json(), default=str)[:300]
        except Exception:
            body_preview = r.text[:200]
        passed = r.status_code in expect
        results.append({"method": method, "path": path,
                        "status": r.status_code, "ms": elapsed,
                        "passed": passed, "body": body_preview})
        print(f"  {method:5s} {path:50s} -> {r.status_code} ({elapsed}ms) "
              f"{'OK' if passed else 'FAIL'}")
        return r
    except Exception as e:
        elapsed = round((time.perf_counter() - started) * 1000)
        print(f"  {method:5s} {path:50s} -> EXC {e!s:.80}")
        results.append({"method": method, "path": path, "status": None,
                        "ms": elapsed, "passed": False, "exception": str(e)})


def main() -> int:
    with httpx.Client(cookies=cookies) as c:
        print("--- /health ---")
        call(c, "GET", "/health/status")
        call(c, "GET", "/health/check")
        call(c, "GET", "/health/api/current")
        call(c, "GET", "/health/api/history")
        call(c, "GET", "/health/api/stats")
        call(c, "GET", "/health/api/alerts")

        print("\n--- /latency ---")
        call(c, "GET", "/latency/api/stats")
        call(c, "GET", "/latency/api/logs")

        print("\n--- /traffic ---")
        call(c, "GET", "/traffic/api/stats")
        call(c, "GET", "/traffic/api/logs")

        print("\n--- /security ---")
        call(c, "GET", "/security/api/data")
        call(c, "GET", "/security/api/login-activity")
        call(c, "GET", "/security/api/active-sessions")

        print("\n--- /api/master-contract ---")
        call(c, "GET", "/api/master-contract/status")
        call(c, "GET", "/api/master-contract/smart-status")

        print("\n--- /api/cache ---")
        call(c, "GET", "/api/cache/status")
        call(c, "GET", "/api/cache/health")

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print(f"\n[summary] {passed}/{total} passed")
    failures = [r for r in results if not r.get("passed")]
    if failures:
        print("--- failures ---")
        for r in failures:
            print(f"  {r['method']} {r['path']} status={r.get('status')} body={r.get('body','')[:200]}")
    (ART / "ops_results.json").write_text(json.dumps({"passed": passed, "total": total, "results": results}, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
