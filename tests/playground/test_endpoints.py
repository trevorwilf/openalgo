"""Playground endpoint discovery for rich broker capability objects."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
import pytz
from flask import Flask

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture
def api_env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_KEY_PEPPER", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")


def _log_in(client, broker: str) -> None:
    with client.session_transaction() as s:
        s["logged_in"] = True
        s["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
        s["broker"] = broker


def test_get_endpoints_reads_broker_type_attribute(api_env, monkeypatch) -> None:
    from blueprints.playground import playground_bp

    app = Flask(__name__, root_path=str(REPO_ROOT))
    app.secret_key = "playground-test"
    app.register_blueprint(playground_bp)

    captured: list[str] = []

    def fake_loader(*, broker_type: str):
        captured.append(broker_type)
        return {"account": [], "orders": [], "data": [], "utilities": [], "websocket": []}

    monkeypatch.setattr("blueprints.playground.load_bruno_endpoints", fake_loader)
    monkeypatch.setattr(
        "utils.plugin_loader.get_broker_capabilities",
        lambda broker: SimpleNamespace(broker_type="us_stock"),
    )

    client = app.test_client()
    _log_in(client, broker="schwab_like")

    response = client.get("/playground/endpoints", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert captured == ["us_stock"]


def test_load_bruno_endpoints_falls_back_to_in_stock_collection(api_env) -> None:
    from blueprints.playground import load_bruno_endpoints

    endpoints = load_bruno_endpoints("us_stock")
    assert sum(len(v) for v in endpoints.values()) > 0
