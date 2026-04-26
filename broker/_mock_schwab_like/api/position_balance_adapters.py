"""Phase 5 v4 — Mock Schwab-LIKE position + balance adapters.

Implements the :class:`BrokerPositionAdapter` and
:class:`BrokerBalanceAdapter` Protocols from
:mod:`domain.broker_market_data`. Backed by deterministic in-memory
fixtures — no network calls.
"""

from __future__ import annotations

from decimal import Decimal

from domain.broker_market_data import (
    AccountContext,
    NormalizedBalance,
    NormalizedPosition,
)


BROKER_CODE = "_mock_schwab_like"


class MockSchwabLikePositionAdapter:
    broker_code = BROKER_CODE

    def get_positions(self, account_ctx: AccountContext) -> list[NormalizedPosition]:
        return [
            NormalizedPosition(
                instrument_id="instrument-XNAS-AAPL",
                venue_code="XNAS",
                canonical_symbol="AAPL",
                quantity=Decimal("10"),
                average_price=Decimal("150.00"),
                market_value=Decimal("1850.00"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("350.00"),
                currency="USD",
                metadata={"source": "mock_schwab_like"},
            ),
            NormalizedPosition(
                instrument_id="instrument-XNAS-MSFT",
                venue_code="XNAS",
                canonical_symbol="MSFT",
                quantity=Decimal("5"),
                average_price=Decimal("400.00"),
                market_value=Decimal("2050.00"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("50.00"),
                currency="USD",
                metadata={"source": "mock_schwab_like"},
            ),
        ]


class MockSchwabLikeBalanceAdapter:
    broker_code = BROKER_CODE

    def get_balance(self, account_ctx: AccountContext) -> NormalizedBalance:
        return NormalizedBalance(
            cash=Decimal("100000.00"),
            equity=Decimal("103900.00"),
            buying_power=Decimal("200000.00"),
            margin_used=Decimal("0"),
            currency="USD",
            metadata={"source": "mock_schwab_like"},
        )


def install_mock_schwab_like_account_adapters() -> None:
    from services.broker_market_data_registry import (
        register_broker_balance_adapter,
        register_broker_position_adapter,
    )

    register_broker_position_adapter(MockSchwabLikePositionAdapter())
    register_broker_balance_adapter(MockSchwabLikeBalanceAdapter())


__all__ = [
    "BROKER_CODE",
    "MockSchwabLikeBalanceAdapter",
    "MockSchwabLikePositionAdapter",
    "install_mock_schwab_like_account_adapters",
]
