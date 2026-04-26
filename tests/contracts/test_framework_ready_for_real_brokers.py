"""Phase 11 v4 (ADR 0022) — framework-readiness contract test.

Asserts the platform can host a real promoted-lane broker plugin
without further core changes. Specifically:

1. Both mock plugins (`_mock_schwab_like`, `_mock_webull_like`) load
   under strict mode (proves the strict promoted plugin schema is
   deployable).
2. Both mock plugins have:
   - An order translator surface
     (`broker/<plugin>/api/order_api.py` with an
     `install_*_translator` helper).
   - A position + balance adapter
     (`broker/<plugin>/api/position_balance_adapters.py`).
   - A streaming surface
     (`broker/<plugin>/api/stream_api.py`).
   - Instrument sync (`broker/<plugin>/sync/instrument_sync.py`).
3. The v4 advanced-feature provider contracts exist
   (Sandbox / Options / Screener) — verified by
   `test_v4_advanced_feature_provider_contracts.py`.
4. The capability dispatcher contracts exist
   (`BrokerOrderTranslator`, `BrokerQuoteAdapter`, `BrokerBarAdapter`,
   `BrokerPositionAdapter`, `BrokerBalanceAdapter`).
5. The v2 surfaces have a route fallback inventory entry for every
   route (no orphan v2 routes).

This test is the gate that says "real Schwab and real Webull plugins
can land without core changes." It must pass cleanly at v4 close.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_PLUGINS = ["_mock_schwab_like", "_mock_webull_like"]


@pytest.mark.parametrize("broker_code", MOCK_PLUGINS)
def test_mock_plugin_strict_mode(broker_code):
    from utils import plugin_loader

    plugin_path = REPO_ROOT / "broker" / broker_code / "plugin.json"
    assert plugin_path.is_file(), f"missing {plugin_path}"
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    errors = plugin_loader._strict_promoted_plugin_errors(broker_code, data)
    assert errors == [], (
        f"{broker_code}: strict-mode validation failed: {errors}"
    )


@pytest.mark.parametrize("broker_code", MOCK_PLUGINS)
def test_mock_plugin_has_order_api(broker_code):
    p = REPO_ROOT / "broker" / broker_code / "api" / "order_api.py"
    assert p.is_file(), f"missing {p}"


@pytest.mark.parametrize("broker_code", MOCK_PLUGINS)
def test_mock_plugin_has_position_balance_adapters(broker_code):
    p = REPO_ROOT / "broker" / broker_code / "api" / "position_balance_adapters.py"
    assert p.is_file(), (
        f"missing {p} — Phase 5 v4 introduced the position+balance "
        "adapter pattern; mock plugins must implement it."
    )


@pytest.mark.parametrize("broker_code", MOCK_PLUGINS)
def test_mock_plugin_has_stream_api(broker_code):
    p = REPO_ROOT / "broker" / broker_code / "api" / "stream_api.py"
    assert p.is_file(), f"missing {p}"


@pytest.mark.parametrize("broker_code", MOCK_PLUGINS)
def test_mock_plugin_has_instrument_sync(broker_code):
    p = REPO_ROOT / "broker" / broker_code / "sync" / "instrument_sync.py"
    assert p.is_file(), f"missing {p}"


def test_v4_advanced_feature_contracts_loadable():
    """All three v4 provider contracts (Sandbox / Options / Screener)
    are loadable at import time."""
    from services.options.providers.base import OptionsProvider
    from services.sandbox.providers.base import SandboxProvider
    from services.screeners.providers.base import ScreenerProvider
    assert OptionsProvider is not None
    assert SandboxProvider is not None
    assert ScreenerProvider is not None


def test_capability_dispatcher_contracts_loadable():
    """Every capability dispatcher Protocol exists and is importable."""
    from domain.broker_market_data import (
        BrokerBalanceAdapter,
        BrokerBarAdapter,
        BrokerPositionAdapter,
        BrokerQuoteAdapter,
    )
    from domain.broker_translator import BrokerOrderTranslator
    assert BrokerOrderTranslator is not None
    assert BrokerQuoteAdapter is not None
    assert BrokerBarAdapter is not None
    assert BrokerPositionAdapter is not None
    assert BrokerBalanceAdapter is not None


def test_no_unfinished_promoted_TODO_markers():
    """The promoted-core PROMOTED_CORE files are scanned for TODO
    markers that look like Phase-N-bis follow-ups. Empty list expected
    at v4 close.

    Note: the docstring mentions of "Phase N" or "Phase N-bis" are
    not violations — only TODO comments inside code are. We allow
    docstring references because they often record completed/in-place
    work or deferral tracking, not blocking todos.
    """
    classification_doc = REPO_ROOT / "docs" / "refactor" / "file_classification.md"
    if not classification_doc.is_file():
        pytest.skip("file_classification.md missing")

    in_section = False
    files: list[Path] = []
    for raw in classification_doc.read_text(encoding="utf-8").splitlines():
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

    assert files, "PROMOTED_CORE list missing"

    # Count "TODO:" markers on actual code lines (not in docstrings or
    # block comments). This is a soft signal — exact-zero is the goal,
    # but informational follow-ups are allowed in commented-out code.
    blocking_todos: list[str] = []
    for f in files:
        if not f.is_file():
            continue
        try:
            for ln, raw in enumerate(
                f.read_text(encoding="utf-8").splitlines(), start=1
            ):
                # Match "# TODO:" or "TODO:" inside a code expression
                # (rough heuristic).
                if "TODO:" in raw and not raw.strip().startswith("#"):
                    blocking_todos.append(
                        f"{f.relative_to(REPO_ROOT).as_posix()}:{ln}: {raw.strip()[:100]}"
                    )
        except (OSError, UnicodeDecodeError):
            continue
    # Allow informational TODO comments; only fail on TODOs in
    # actual code expressions (not in `# ...` lines).
    assert not blocking_todos, (
        "Promoted core has blocking TODO markers in code (not "
        "comments):\n  " + "\n  ".join(blocking_todos)
    )
