"""Settings API + DB support for market-region plugins."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytz
from flask import Flask

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture
def settings_app(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "settings.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    from database import settings_db
    from utils import region_loader

    settings_db._reset_engine_for_tests()
    settings_db.init_db()
    region_loader._reset_cache_for_tests()
    region_loader.load_market_regions(str(REPO_ROOT / "market_regions"))

    app = Flask(__name__, root_path=str(REPO_ROOT))
    app.secret_key = "market-region-test"

    from blueprints.settings import settings_bp

    app.register_blueprint(settings_bp)
    yield app

    settings_db.db_session.remove()
    settings_db.clear_settings_cache()
    region_loader._reset_cache_for_tests()


def _log_in(client, *, broker: str | None = None) -> None:
    with client.session_transaction() as s:
        s["logged_in"] = True
        s["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
        if broker:
            s["broker"] = broker


def test_market_regions_endpoint_lists_installed_regions(settings_app, monkeypatch) -> None:
    from services import market_region_service

    monkeypatch.setattr(
        market_region_service,
        "get_broker_capabilities",
        lambda broker: SimpleNamespace(supported_regions=["us"]),
    )

    client = settings_app.test_client()
    _log_in(client, broker="schwab_like")

    response = client.get("/settings/market-regions", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["default_region"] == "india"
    assert {region["region_code"] for region in body["regions"]} >= {"india", "us", "eu", "uk"}

    us_region = next(region for region in body["regions"] if region["region_code"] == "us")
    india_region = next(region for region in body["regions"] if region["region_code"] == "india")
    assert us_region["supported_by_active_broker"] is True
    assert india_region["supported_by_active_broker"] is False


def test_setting_default_market_region_persists(settings_app) -> None:
    client = settings_app.test_client()
    _log_in(client)

    response = client.post(
        "/settings/default-region",
        json={"region_code": "us"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["default_region"] == "us"

    follow_up = client.get("/settings/default-region", headers={"Accept": "application/json"})
    assert follow_up.status_code == 200
    assert follow_up.get_json()["default_region"] == "us"


def test_setting_unknown_market_region_fails_cleanly(settings_app) -> None:
    client = settings_app.test_client()
    _log_in(client)

    response = client.post(
        "/settings/default-region",
        json={"region_code": "moon"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    assert "Unknown market region" in response.get_json()["error"]


def test_init_db_migrates_default_market_region_column(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy_settings.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, analyze_mode BOOLEAN)")
    conn.execute("INSERT INTO settings (id, analyze_mode) VALUES (1, 0)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from database import settings_db

    settings_db._reset_engine_for_tests()
    settings_db.init_db()

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    row = conn.execute("SELECT default_market_region FROM settings WHERE id = 1").fetchone()
    conn.close()

    assert "default_market_region" in columns
    assert row == ("india",)
