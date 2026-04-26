"""Phase 5 v4 — Mock Webull-LIKE position + balance adapters."""

from __future__ import annotations

from decimal import Decimal

from domain.broker_market_data import (
    AccountContext,
    NormalizedBalance,
    NormalizedPosition,
)


BROKER_CODE = "_mock_webull_like"


class MockWebullLikePositionAdapter:
    broker_code = BROKER_CODE

    def get_positions(self, account_ctx: AccountContext) -> list[NormalizedPosition]:
        return [
            NormalizedPosition(
                instrument_id="instrument-XNAS-MSFT",
                venue_code="XNAS",
                canonical_symbol="MSFT",
                quantity=Decimal("12"),
                average_price=Decimal("395.00"),
                market_value=Decimal("4920.00"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("180.00"),
                currency="USD",
                metadata={"source": "mock_webull_like"},
            ),
        ]


class MockWebullLikeBalanceAdapter:
    broker_code = BROKER_CODE

    def get_balance(self, account_ctx: AccountContext) -> NormalizedBalance:
        return NormalizedBalance(
            cash=Decimal("50000.00"),
            equity=Decimal("54920.00"),
            buying_power=Decimal("100000.00"),
            margin_used=Decimal("0"),
            currency="USD",
            metadata={"source": "mock_webull_like"},
        )


def install_mock_webull_like_account_adapters() -> None:
    from services.broker_market_data_registry import (
        register_broker_balance_adapter,
        register_broker_position_adapter,
    )

    register_broker_position_adapter(MockWebullLikePositionAdapter())
    register_broker_balance_adapter(MockWebullLikeBalanceAdapter())


__all__ = [
    "BROKER_CODE",
    "MockWebullLikeBalanceAdapter",
    "MockWebullLikePositionAdapter",
    "install_mock_webull_like_account_adapters",
]
