"""Fixtures shared by the region_loader test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest


@pytest.fixture
def reset_loader_state():
    from utils import region_loader

    region_loader._reset_cache_for_tests()
    yield
    region_loader._reset_cache_for_tests()


@pytest.fixture
def make_region_tree(
    tmp_path: Path,
) -> Callable[[dict[str, dict[str, Any] | str | None]], Path]:
    def _make(specs: dict[str, dict[str, Any] | str | None]) -> Path:
        region_dir = tmp_path / "market_regions"
        region_dir.mkdir(parents=True, exist_ok=True)
        for name, contents in specs.items():
            d = region_dir / name
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
    prev = os.getcwd()
    try:
        os.chdir(tmp_path)
        yield tmp_path
    finally:
        os.chdir(prev)
