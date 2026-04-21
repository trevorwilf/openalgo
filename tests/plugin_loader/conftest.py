"""Fixtures shared by the plugin_loader test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def reset_loader_state():
    """Reset the plugin_loader module-level cache between tests."""
    from utils import plugin_loader

    plugin_loader._reset_cache_for_tests()
    yield
    plugin_loader._reset_cache_for_tests()


@pytest.fixture
def real_broker_dir() -> Path:
    """Path to the real broker/ directory in this repo."""
    return REPO_ROOT / "broker"


@pytest.fixture
def real_plugin_files(real_broker_dir: Path) -> list[Path]:
    return sorted(real_broker_dir.glob("*/plugin.json"))


@pytest.fixture
def make_broker_tree(
    tmp_path: Path,
) -> Callable[[dict[str, dict[str, Any] | str]], Path]:
    """Factory that builds a synthetic `broker/` tree under `tmp_path`.

    The argument is a dict `{broker_name: plugin_contents}`. If the
    contents is a dict, it's JSON-dumped into plugin.json. If it's a
    string, it's written verbatim (useful for malformed JSON).
    `None` skips creating plugin.json entirely.
    """

    def _make(specs: dict[str, dict[str, Any] | str | None]) -> Path:
        broker_dir = tmp_path / "broker"
        broker_dir.mkdir(parents=True, exist_ok=True)
        for name, contents in specs.items():
            d = broker_dir / name
            d.mkdir(exist_ok=True)
            if contents is None:
                continue
            plugin_path = d / "plugin.json"
            if isinstance(contents, str):
                plugin_path.write_text(contents, encoding="utf-8")
            else:
                plugin_path.write_text(json.dumps(contents), encoding="utf-8")
        return tmp_path

    return _make


@pytest.fixture
def chdir(tmp_path: Path):
    """Run a test in `tmp_path` so `_broker_root_path("broker")` resolves there
    when no Flask app context is available."""
    prev = os.getcwd()
    try:
        os.chdir(tmp_path)
        yield tmp_path
    finally:
        os.chdir(prev)
