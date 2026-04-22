"""With API_V2 off, every /api/v2 route returns 404.

This is the contract the playbook requires for production safety —
the flag is default-off and the namespace must be invisible.
"""

from __future__ import annotations


def test_capabilities_404_when_flag_off(flask_app_flag_off) -> None:
    client = flask_app_flag_off.test_client()
    assert client.get("/api/v2/capabilities").status_code == 404


def test_instruments_search_404_when_flag_off(flask_app_flag_off) -> None:
    client = flask_app_flag_off.test_client()
    assert client.get("/api/v2/instruments/search?q=RELIANCE").status_code == 404


def test_quotes_404_when_flag_off(flask_app_flag_off) -> None:
    client = flask_app_flag_off.test_client()
    assert (
        client.post("/api/v2/quotes", json={"instruments": []}).status_code == 404
    )


def test_orders_404_when_flag_off(flask_app_flag_off) -> None:
    client = flask_app_flag_off.test_client()
    assert client.post("/api/v2/orders", json={}).status_code == 404
