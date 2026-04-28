"""Phase 3 v6 (ADR 0027 + EU region) — EU options provider stub.

Per the EU region plugin's ``feature_flags.option_chain_enabled =
false``, options are not implemented for EU venues in v6. This stub
satisfies the OptionsProvider Protocol so the dispatcher can resolve
``region="eu"`` and surface a structured
``option_chain_disabled_in_region`` error to the caller, instead of
fail-closing on registry lookup.

Real EU options semantics (Eurex futures + options grammar, MiFID II
constraints, multiple settlement currencies across venues) are out
of v6 scope.
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

REGION_CODE = "eu"


class EUOptionsNotImplemented(DomainError):
    """Raised when an EU options operation is invoked.

    The dispatcher routes the caller here (the provider IS registered)
    so the caller sees a structured error rather than a registry miss.
    """

    code = ErrorCode.OPTION_CHAIN_DISABLED_IN_REGION

    def __init__(self, op: str) -> None:
        self.op = op
        super().__init__(
            f"EU options provider stub: {op!r} is not implemented in v6. "
            "EU region plugin declares option_chain_enabled=false. "
            "See ADR 0027."
        )


class EUOptionsProvider:
    """Minimal EU options stub. Every method raises the structured
    options_disabled_in_region error so the caller sees a clean
    'feature unavailable in region' surface."""

    region_code = REGION_CODE

    def parse_option_symbol(self, symbol: str) -> OptionContract:
        raise EUOptionsNotImplemented("parse_option_symbol")

    def format_option_symbol(self, contract: OptionContract) -> str:
        raise EUOptionsNotImplemented("format_option_symbol")

    def list_expiries(self, underlying: str, asof: date) -> list[date]:
        raise EUOptionsNotImplemented("list_expiries")

    def get_chain(self, underlying: str, expiry: date) -> OptionChain:
        raise EUOptionsNotImplemented("get_chain")

    def compute_greeks(
        self, contract: OptionContract, market: MarketSnapshot, iv: Decimal,
    ) -> Greeks:
        raise EUOptionsNotImplemented("compute_greeks")

    def compute_iv(
        self, contract: OptionContract, premium: Decimal, market: MarketSnapshot,
    ) -> Decimal:
        raise EUOptionsNotImplemented("compute_iv")

    def compute_oi_profile(self, underlying: str, expiry: date) -> OIProfile:
        raise EUOptionsNotImplemented("compute_oi_profile")

    def supported_strategies(self) -> set[str]:
        # Empty set — provider declares no supported strategies.
        return set()

    def lot_size_for(self, contract: OptionContract) -> int:
        raise EUOptionsNotImplemented("lot_size_for")


__all__ = ["EUOptionsNotImplemented", "EUOptionsProvider", "REGION_CODE"]
