"""utils/broker_context.current_broker_code fallback order."""

from __future__ import annotations


def test_returns_env_when_no_flask(monkeypatch) -> None:
    from utils.broker_context import current_broker_code

    monkeypatch.setenv("BROKER_NAME", "zerodha")
    assert current_broker_code() == "zerodha"


def test_returns_none_when_nothing_set(monkeypatch) -> None:
    from utils.broker_context import current_broker_code

    monkeypatch.delenv("BROKER_NAME", raising=False)
    assert current_broker_code() is None


def test_flask_session_wins(monkeypatch) -> None:
    from flask import Flask

    from utils.broker_context import current_broker_code

    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session

        session["broker"] = "dhan"
        monkeypatch.setenv("BROKER_NAME", "zerodha")
        assert current_broker_code() == "dhan"


def test_env_fallback_when_session_empty(monkeypatch) -> None:
    from flask import Flask

    from utils.broker_context import current_broker_code

    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        monkeypatch.setenv("BROKER_NAME", "angelone")
        assert current_broker_code() == "angelone"
