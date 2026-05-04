"""Regression: Alpaca's JSON error body is surfaced through the
HTTPStatusError message instead of being discarded.

Without ``_raise_with_alpaca_message``, the v1 bridge's
``broker_error`` envelope shows just ``Client error '422
Unprocessable Entity'``. With it, the broker's ``message`` field
("stop price must be greater than current price",
"insufficient buying power", etc.) reaches the operator.
"""

from __future__ import annotations

import httpx
import pytest

from broker.alpaca.api.order_api import _raise_with_alpaca_message


def _resp(status: int, body: dict | None) -> httpx.Response:
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    if body is None:
        return httpx.Response(status, request=request)
    return httpx.Response(status, json=body, request=request)


def test_no_raise_on_2xx():
    _raise_with_alpaca_message(_resp(200, {"id": "abc"}))
    _raise_with_alpaca_message(_resp(204, None))


def test_4xx_with_alpaca_message_appears_in_exception():
    body = {"code": 42210000, "message": "stop price must be greater than current price"}
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _raise_with_alpaca_message(_resp(422, body))
    assert "stop price must be greater than current price" in str(exc.value)
    assert "42210000" in str(exc.value)


def test_4xx_without_alpaca_message_falls_back_to_default():
    """When the body has no ``message``, behave like raise_for_status."""
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _raise_with_alpaca_message(_resp(422, {"foo": "bar"}))
    # Default httpx message style.
    assert "422" in str(exc.value)


def test_4xx_with_unparseable_body():
    """Non-JSON error body — fall back to httpx default raise."""
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    resp = httpx.Response(500, content=b"<html>500</html>", request=request)
    with pytest.raises(httpx.HTTPStatusError):
        _raise_with_alpaca_message(resp)
