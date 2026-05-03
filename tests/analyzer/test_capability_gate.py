"""The `@requires_capability("supports_analyzer")` decorator gates every
analyzer/sandbox route cleanly.

Strategy:
- Build a minimal Flask app.
- Register a tiny test route that wears the decorator.
- Toggle the mocked capability and assert 200 vs 403.

Also sanity-check that every route under blueprints/analyzer.py and
blueprints/sandbox.py is decorated by grepping the source.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest
from flask import jsonify

from utils.capability_guards import requires_capability

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------


def test_decorator_allows_when_capability_true(app, capability_factory) -> None:
    caps = capability_factory(supports_analyzer=True)

    @app.route("/_probe")
    @requires_capability("supports_analyzer")
    def _probe():
        return jsonify({"ok": True})

    with mock.patch(
        "utils.capability_guards.get_broker_capabilities",
        create=True,
    ):
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["broker"] = "zerodha"
            with mock.patch(
                "utils.plugin_loader.get_broker_capabilities", return_value=caps
            ):
                resp = c.get("/_probe")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_decorator_blocks_when_capability_false(app, capability_factory) -> None:
    caps = capability_factory(supports_analyzer=False)

    @app.route("/_probe")
    @requires_capability("supports_analyzer")
    def _probe():
        return jsonify({"ok": True})

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "deltaexchange"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=caps
        ):
            resp = c.get("/_probe")

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["code"] == "CAPABILITY_UNAVAILABLE"
    assert body["capability"] == "supports_analyzer"
    assert "deltaexchange" in body["message"]


def test_decorator_blocks_when_no_broker_in_session(app, capability_factory) -> None:
    @app.route("/_probe")
    @requires_capability("supports_analyzer")
    def _probe():
        return jsonify({"ok": True})

    # No session → capability lookup returns None → fail-closed 403.
    with app.test_client() as c:
        resp = c.get("/_probe")
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["code"] == "CAPABILITY_UNAVAILABLE"


def test_decorator_blocks_when_capabilities_missing(app, capability_factory) -> None:
    @app.route("/_probe")
    @requires_capability("supports_analyzer")
    def _probe():
        return jsonify({"ok": True})

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "newbroker"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=None
        ):
            resp = c.get("/_probe")
    assert resp.status_code == 403


def test_decorator_respects_custom_status(app, capability_factory) -> None:
    caps = capability_factory(supports_analyzer=False)

    @app.route("/_probe")
    @requires_capability("supports_analyzer", status=451)
    def _probe():
        return jsonify({"ok": True})

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "deltaexchange"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=caps
        ):
            resp = c.get("/_probe")
    assert resp.status_code == 451


def test_decorator_handles_exception_in_loader(app) -> None:
    @app.route("/_probe")
    @requires_capability("supports_analyzer")
    def _probe():
        return jsonify({"ok": True})

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "zerodha"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities",
            side_effect=RuntimeError("loader broke"),
        ):
            resp = c.get("/_probe")
    # Loader exception → caps is None → 403 (fail closed).
    assert resp.status_code == 403


def test_feature_dict_fallback_triggers(app, capability_factory) -> None:
    """If the named attribute isn't a first-class bool, has_capability
    checks the `features` dict. Covered via the stub's behaviour."""
    def has_capability(name: str) -> bool:
        return name == "custom_flag"

    caps = type("C", (), {"has_capability": staticmethod(has_capability)})()

    @app.route("/_probe")
    @requires_capability("custom_flag")
    def _probe():
        return jsonify({"ok": True})

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["broker"] = "zerodha"
        with mock.patch(
            "utils.plugin_loader.get_broker_capabilities", return_value=caps
        ):
            resp = c.get("/_probe")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Static coverage: every analyzer/sandbox route must have the decorator.
# ---------------------------------------------------------------------------


BLUEPRINT_FILES = [
    REPO_ROOT / "blueprints" / "analyzer.py",
    # Phase 9-bis-2 final-cleanup (T-35 push) relocated the sandbox
    # blueprint to market_regions/india/legacy_v1/blueprints/sandbox.py.
    # The blueprints/sandbox.py path is a sys.modules-aliasing shim
    # with no route definitions, so the AST scan must look at the new
    # location.
    REPO_ROOT
    / "market_regions"
    / "india"
    / "legacy_v1"
    / "blueprints"
    / "sandbox.py",
]


def _decorator_names(func: ast.FunctionDef) -> list[str]:
    """Return the stringified decorator call expressions for a function."""
    out: list[str] = []
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call):
            # Look for `requires_capability("supports_analyzer")`
            func_name = _dotted_name(dec.func)
            out.append(func_name or "")
        else:
            out.append(_dotted_name(dec) or "")
    return out


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _functions_with_route_decorator(py_file: Path) -> list[ast.FunctionDef]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    out: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    name = _dotted_name(dec.func)
                    if name and name.endswith(".route"):
                        out.append(node)
                        break
    return out


@pytest.mark.parametrize("py_file", BLUEPRINT_FILES)
def test_every_route_has_requires_capability(py_file: Path) -> None:
    """No route in analyzer.py / sandbox.py may be missing the decorator."""
    routes = _functions_with_route_decorator(py_file)
    assert routes, f"expected at least one route in {py_file.name}"
    missing: list[str] = []
    for fn in routes:
        names = _decorator_names(fn)
        if not any("requires_capability" in n for n in names):
            missing.append(fn.name)
    assert missing == [], (
        f"{py_file.name} is missing @requires_capability on: {missing}"
    )
