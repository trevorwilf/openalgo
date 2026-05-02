"""JSON Schema enforcement at startup.

* Every real plugin.json passes validation.
* An invalid synthetic plugin.json is skipped with a log error; the
  loader still returns successfully and valid plugins alongside it
  remain usable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_PLUGINS = sorted((REPO_ROOT / "broker").glob("*/plugin.json"))


@pytest.mark.parametrize(
    "plugin_path", REAL_PLUGINS, ids=[p.parent.name for p in REAL_PLUGINS]
)
def test_real_plugins_pass_schema(plugin_path: Path) -> None:
    data = json.loads(plugin_path.read_text(encoding="utf-8"))
    errors = plugin_loader._validate_plugin_json(data)
    assert errors == [], (
        f"{plugin_path.parent.name} plugin.json failed schema: {errors}"
    )


def test_invalid_shape_skipped_without_crash(
    make_broker_tree, chdir, reset_loader_state, caplog
) -> None:
    """A plugin.json with a type error is logged, skipped, and does not
    crash load_broker_capabilities. Valid siblings are still loaded."""
    make_broker_tree(
        {
            "good": {
                "Plugin Name": "good",
                "broker_type": "IN_stock",
                "supported_regions": ["india"],
                "supported_exchanges": ["NSE"],
                "leverage_config": False,
            },
            "bad": {
                "Plugin Name": "bad",
                "broker_type": "IN_stock",
                "supported_regions": ["india"],
                # Wrong type: should be list of strings
                "supported_exchanges": "NSE,BSE",
                "leverage_config": False,
            },
            # Broker without plugin.json — should be ignored silently
            "no_plugin": None,
        }
    )

    with caplog.at_level("ERROR"):
        caps = plugin_loader.load_broker_capabilities("broker")

    assert "good" in caps
    assert "bad" not in caps
    assert "bad" in plugin_loader._skipped_brokers_for_tests()
    # The error log should mention the offending broker
    messages = " ".join(rec.getMessage() for rec in caplog.records)
    assert "bad" in messages


def test_malformed_json_skipped(
    make_broker_tree, chdir, reset_loader_state, caplog
) -> None:
    make_broker_tree(
        {
            "valid": {
                "Plugin Name": "valid",
                "broker_type": "IN_stock",
                "supported_regions": ["india"],
                "supported_exchanges": ["NSE"],
            },
            "corrupt": "{not valid json",
        }
    )

    with caplog.at_level("ERROR"):
        caps = plugin_loader.load_broker_capabilities("broker")

    assert "valid" in caps
    assert "corrupt" not in caps


def test_missing_broker_directory_returns_empty(
    chdir, reset_loader_state, caplog, tmp_path
) -> None:
    """No broker/ dir → empty dict, logged warning, no exception."""
    # tmp_path is cwd but has no broker/ subdir.
    with caplog.at_level("WARNING"):
        caps = plugin_loader.load_broker_capabilities("broker")
    assert caps == {}


def test_skipped_brokers_excluded_from_auth_dict(
    make_broker_tree, chdir, reset_loader_state
) -> None:
    make_broker_tree(
        {
            "good": {
                "Plugin Name": "good",
                "broker_type": "IN_stock",
                "supported_regions": ["india"],
                "supported_exchanges": ["NSE"],
                "leverage_config": False,
            },
            "bad": {
                "Plugin Name": "bad",
                "broker_type": "IN_stock",
                "supported_regions": ["india"],
                "supported_exchanges": 123,  # wrong type
            },
        }
    )
    plugin_loader.load_broker_capabilities("broker")
    auth_dict = plugin_loader.load_broker_auth_functions("broker")
    assert "bad" not in auth_dict._broker_names
    assert "good" in auth_dict._broker_names
