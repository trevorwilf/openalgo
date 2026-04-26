"""E2E test fixtures — re-export the flask_app fixture from
tests/api_v2/conftest.py so e2e tests can use the same minimal Flask
app shell.
"""

from __future__ import annotations

from tests.api_v2.conftest import flag_off, flag_on, flask_app, flask_app_flag_off  # noqa: F401
