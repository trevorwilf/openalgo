"""T-04 — v1 compat bridge no longer hard-codes MIS/XNAS defaults.

Phase 2 contract: ``services.v1_compat_bridge`` reads venue and
product defaults from ``BrokerCapabilities`` instead of hard-coded
India literals. Specifically the 6 sites named in the engineering
handoff (lines ~204, 358, 362, 688, 762, 773, 823 in the pre-T-04
file) are eliminated.

The ``_VENUE_ALIASES`` translation table (the dict literal at lines
~80-180) and the ``_alias_venue`` helper's defensive default are
NOT in scope — the prompt explicitly preserves them as the
documented venue-code aliasing concern, not silent defaults.

Detection: scan for the silent-default pattern ``or "MIS"`` /
``or "XNAS"`` which is the idiom T-04 eliminates. Use AST string-
literal walking so docstrings and comments are skipped automatically.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_BRIDGE = (
    Path(__file__).resolve().parents[2] / "services" / "v1_compat_bridge.py"
)


def _ast_string_literals(source: str) -> list[tuple[int, str]]:
    """Walk the AST and return ``(lineno, value)`` for every string
    constant at a non-docstring position."""
    tree = ast.parse(source)
    docstring_locs: set[int] = set()
    # Module docstring
    if isinstance(tree.body[0] if tree.body else None, ast.Expr) and isinstance(
        tree.body[0].value, ast.Constant
    ) and isinstance(tree.body[0].value.value, str):
        docstring_locs.add(tree.body[0].value.lineno)
    # Function / class docstrings
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                # Approximate: tag every line spanned by the docstring.
                ds = node.body[0].value
                end = getattr(ds, "end_lineno", ds.lineno)
                for ln in range(ds.lineno, end + 1):
                    docstring_locs.add(ln)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.lineno not in docstring_locs
        ):
            out.append((node.lineno, node.value))
    return out


def test_no_silent_or_mis_default() -> None:
    """No ``or "MIS"`` silent-fallback expression remains."""
    text = _BRIDGE.read_text(encoding="utf-8")
    pattern = re.compile(r'\bor\s+["\']MIS["\']')
    matches = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Skip comments + docstring/markdown lines (they're narrative).
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if pattern.search(line):
            matches.append(f"v1_compat_bridge.py:{lineno}: {line.strip()}")
    assert not matches, (
        "v1_compat_bridge.py contains a silent ``or \"MIS\"`` default. "
        "T-04 requires reading from BrokerCapabilities.default_product_code. "
        f"Hits:\n  " + "\n  ".join(matches)
    )


def test_no_silent_or_xnas_default() -> None:
    """No ``or "XNAS"`` silent-fallback expression remains."""
    text = _BRIDGE.read_text(encoding="utf-8")
    pattern = re.compile(r'\bor\s+["\']XNAS["\']')
    matches = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if pattern.search(line):
            matches.append(f"v1_compat_bridge.py:{lineno}: {line.strip()}")
    assert not matches, (
        "v1_compat_bridge.py contains a silent ``or \"XNAS\"`` default. "
        "T-04 requires reading from BrokerCapabilities.default_venue_code. "
        f"Hits:\n  " + "\n  ".join(matches)
    )


def test_capability_resolvers_present() -> None:
    """The two T-04 helpers exist and are importable."""
    from services.v1_compat_bridge import (
        _broker_default_product_code,
        _broker_default_venue_code,
    )
    assert callable(_broker_default_venue_code)
    assert callable(_broker_default_product_code)


def test_alpaca_resolves_via_capabilities():
    """Alpaca declares ``default_venue_code`` and
    ``default_product_code`` in plugin.json — the resolvers return
    those values, not literal MIS/XNAS."""
    from services.v1_compat_bridge import (
        _broker_default_product_code,
        _broker_default_venue_code,
    )
    venue = _broker_default_venue_code("alpaca")
    product = _broker_default_product_code("alpaca")
    assert venue == "XNAS"
    assert product == "DAY"


def test_unknown_broker_raises_capability_error():
    """Unknown broker → BrokerCapabilityError, not a silent India
    default."""
    from domain.errors import BrokerCapabilityError
    from services.v1_compat_bridge import _broker_default_venue_code

    with pytest.raises(BrokerCapabilityError) as exc:
        _broker_default_venue_code("nonexistent_broker_xyz")
    assert "nonexistent_broker_xyz" in str(exc.value)
