"""Share the api_v2 `flask_app` fixture with observability tests."""

from __future__ import annotations

# Re-export so pytest discovers the fixture here too.
from tests.api_v2.conftest import (  # noqa: F401
    client,
    flag_off,
    flag_on,
    flask_app,
    flask_app_flag_off,
)
