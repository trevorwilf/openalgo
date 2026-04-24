"""GET /api/broker/rules — returns the rule matrix for the active broker."""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask, session as flask_session

from database import broker_rules_repo


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flask:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rules.db'}")
    broker_rules_repo._reset_engine_for_tests()
    broker_rules_repo.init_broker_rules_tables()

    # Bypass the session-validity decorator for testing.
    monkeypatch.setattr(
        "utils.session.check_session_validity",
        lambda f: f,
    )
    # Re-import the blueprint AFTER monkeypatch so the decorator is
    # the stub.
    import importlib

    import blueprints.broker_credentials as mod

    importlib.reload(mod)

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(mod.broker_credentials_bp)
    yield app
    broker_rules_repo._reset_engine_for_tests()


def _seed_alpaca_rule():
    broker_rules_repo.rules_upsert(
        broker_code="alpaca",
        venue_code=None,
        asset_class="EQUITY",
        session_name="REGULAR",
        allowed_order_types=["MARKET", "LIMIT"],
        allowed_time_in_force=["DAY", "GTC"],
        allows_fractional=True,
        allows_notional=True,
        allows_short=True,
    )


def test_returns_400_without_broker_in_session(app):
    client = app.test_client()
    resp = client.get("/api/broker/rules")
    assert resp.status_code == 400


def test_returns_empty_list_when_no_rules_seeded(app):
    with app.test_client() as client:
        with client.session_transaction() as s:
            s["broker"] = "alpaca"
            s["logged_in"] = True
        resp = client.get("/api/broker/rules")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"] == []


def test_returns_seeded_rules(app):
    _seed_alpaca_rule()
    with app.test_client() as client:
        with client.session_transaction() as s:
            s["broker"] = "alpaca"
            s["logged_in"] = True
        resp = client.get("/api/broker/rules")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert len(body["data"]) == 1
    rule = body["data"][0]
    assert rule["asset_class"] == "EQUITY"
    assert set(rule["allowed_order_types"]) == {"MARKET", "LIMIT"}
    assert set(rule["allowed_time_in_force"]) == {"DAY", "GTC"}
    assert rule["allows_fractional"] is True
    assert rule["allows_notional"] is True
