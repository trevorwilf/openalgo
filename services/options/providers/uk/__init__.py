"""Phase 3 v6 (ADR 0027 + UK region) — UK options provider stub.

Per the UK region plugin's ``feature_flags.option_chain_enabled =
false``, options are not implemented for UK venues in v6. This stub
satisfies the OptionsProvider Protocol so the dispatcher can resolve
``region="uk"`` and surface a structured
``option_chain_disabled_in_region`` error to the caller, instead of
fail-closing on registry lookup.

Real LSE / ICE options semantics are out of v6 scope.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from domain.errors import DomainError, ErrorCode
from domain.options import (
    Greeks,
    MarketSnapshot,
    OIProfile,
    OptionChain,
    OptionContract,
)

REGION_CODE = "uk"


class UKOptionsNotImplemented(DomainError):
    """Raised when a UK options operation is invoked."""

    code = ErrorCode.OPTION_CHAIN_DISABLED_IN_REGION

    def __init__(self, op: str) -> None:
        self.op = op
        super().__init__(
            f"UK options provider stub: {op!r} is not implemented in v6. "
            "UK region plugin declares option_chain_enabled=false. "
            "See ADR 0027."
        )


class UKOptionsProvider:
    """Minimal UK options stub. Every method raises the structured
    option_chain_disabled_in_region error."""

    region_code = REGION_CODE

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        raise UKOptionsNotImplemented("parse_option_symbol")

    def format_option_symbol(self, contract: OptionContract) -> str:
        raise UKOptionsNotImplemented("format_option_symbol")

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        raise UKOptionsNotImplemented("list_expiries")

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        raise UKOptionsNotImplemented("get_chain")

    def compute_greeks(
        self, contract: OptionContract, market: MarketSnapshot, iv: Decimal,
    ) -> Greeks:
        raise UKOptionsNotImplemented("compute_greeks")

    def compute_iv(
        self, contract: OptionContract, premium: Decimal, market: MarketSnapshot,
    ) -> Decimal:
        raise UKOptionsNotImplemented("compute_iv")

    def compute_oi_profile(self, underlying: str, expiry: date) -> OIProfile:
        raise UKOptionsNotImplemented("compute_oi_profile")

    def supported_strategies(self) -> set[str]:
        return set()

    def lot_size_for(self, contract: OptionContract) -> int:
        raise UKOptionsNotImplemented("lot_size_for")


__all__ = ["REGION_CODE", "UKOptionsNotImplemented", "UKOptionsProvider"]
