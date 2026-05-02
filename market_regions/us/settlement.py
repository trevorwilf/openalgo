"""US settlement conventions — Phase 7b T-30 build-out.

T+1 for US cash equities since 28 May 2024 (SEC Rule 15c6-2 amendment;
shortened from T+2). T+1 for listed options. T+0 for cash markets
(money market funds settling same-day).

This is data-only. The runtime resolver is in
:mod:`services.sandbox.providers.us` (sandbox) and individual broker
plugins (live trading).
"""

from __future__ import annotations


CASH_EQUITY_SETTLEMENT: str = "T+1"
"""Post-May 2024 SEC Rule 15c6-2 amendment; previously T+2."""

LISTED_OPTIONS_SETTLEMENT: str = "T+1"

MUTUAL_FUND_SETTLEMENT: str = "T+1"


SETTLEMENT_BY_INSTRUMENT_KIND: dict[str, str] = {
    "EQUITY": CASH_EQUITY_SETTLEMENT,
    "OPTION": LISTED_OPTIONS_SETTLEMENT,
    "MUTUAL_FUND": MUTUAL_FUND_SETTLEMENT,
    "FUTURE": "T+0",  # Futures cash-settled daily via mark-to-market
}


__all__ = [
    "CASH_EQUITY_SETTLEMENT",
    "LISTED_OPTIONS_SETTLEMENT",
    "MUTUAL_FUND_SETTLEMENT",
    "SETTLEMENT_BY_INSTRUMENT_KIND",
]
