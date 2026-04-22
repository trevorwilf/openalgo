"""Fixtures for Phase 7 capability-gate tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask import Flask


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "phase7-test"
    return app


@pytest.fixture
def capability_factory():
    """Build a minimal capability stub — only `has_capability` + the
    attribute access the decorator needs. Keeps tests decoupled from
    the full pydantic model."""
    def _make(**flags: bool):
        def has_capability(name: str) -> bool:
            return bool(flags.get(name, False))
        return SimpleNamespace(has_capability=has_capability, **flags)
    return _make
