"""Fixtures for Phase 6 /api/v2 contract tests.

The tests construct a minimal Flask app, register the v2 blueprint
directly (bypassing the full app.py import graph), and drive it with
Flask's test client. This keeps the tests hermetic and fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_V2", raising=False)


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_V2", "1")


@pytest.fixture
def flask_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag_on):
    """Minimal Flask app with the v2 blueprint registered."""
    from flask import Flask

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'phase6.db'}")
    from database import broker_rules_repo, instruments_repo, venue_schedule_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()
    broker_rules_repo._reset_engine_for_tests()
    broker_rules_repo.init_broker_rules_tables()
    venue_schedule_repo.init_venue_schedule_tables()

    app = Flask(__name__)
    app.secret_key = "phase6-test"

    from restx_api.v2 import register_api_v2

    registered = register_api_v2(app)
    assert registered is True
    yield app
    instruments_repo._reset_engine_for_tests()
    broker_rules_repo._reset_engine_for_tests()


@pytest.fixture
def flask_app_flag_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag_off):
    """Flask app built WITHOUT registering v2 — flag-off scenario."""
    from flask import Flask

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'phase6_off.db'}")
    from database import instruments_repo

    instruments_repo._reset_engine_for_tests()
    instruments_repo.init_instrument_tables()

    app = Flask(__name__)
    app.secret_key = "phase6-off"

    from restx_api.v2 import register_api_v2

    registered = register_api_v2(app)
    assert registered is False
    yield app
    instruments_repo._reset_engine_for_tests()


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def register_fake_us_adapters():
    """Phase 2 v3 — register/deregister the FakeUS quote+bar adapters
    cleanly per test. Tests that need a registered adapter for the
    promoted quote/bar dispatch use this fixture."""
    from services.broker_market_data_registry import (
        clear_market_data_registries_for_tests,
    )
    from tests.fakes.fake_us_market_data import install_fake_us_market_data

    clear_market_data_registries_for_tests()
    quote, bar = install_fake_us_market_data()
    yield quote, bar
    clear_market_data_registries_for_tests()
