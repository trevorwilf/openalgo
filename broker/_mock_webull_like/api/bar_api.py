"""Mock Webull-LIKE bar adapter — deterministic 3-bar window."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from domain.account_context import AccountContext
from domain.broker_market_data import (
    NormalizedBar,
    NormalizedBarRequest,
)

BROKER_CODE = "_mock_webull_like"


class MockWebullLikeBarAdapter:
    broker_code = BROKER_CODE

    def get_bars(
        self,
        instrument: Any,
        request: NormalizedBarRequest,
        account_ctx: AccountContext,
    ) -> list[NormalizedBar]:
        out: list[NormalizedBar] = []
        step = timedelta(minutes=1)
        base = Decimal("400.00")
        for i in range(3):
            out.append(
                NormalizedBar(
                    ts=request.start + step * i,
                    open=base + Decimal(i) / 10,
                    high=base + Decimal(i) / 10 + Decimal("0.10"),
                    low=base + Decimal(i) / 10 - Decimal("0.10"),
                    close=base + Decimal(i) / 10 + Decimal("0.05"),
                    volume=Decimal("500"),
                )
            )
        return out


__all__ = ["BROKER_CODE", "MockWebullLikeBarAdapter"]
