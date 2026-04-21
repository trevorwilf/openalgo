"""Currency enum and CurrencyAmount value object.

`Currency` is a StrEnum of ISO-4217 fiat codes and common crypto codes.
Property helpers (`is_fiat`, `is_crypto`, `decimals`) let callers make
rounding/display decisions without hardcoding tables at call sites.

`CurrencyAmount` is a pydantic model that pairs a `Decimal` amount with
a `Currency`. It explicitly rejects `float` construction to prevent
binary-floating-point rounding surprises in order sizing.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Currency(StrEnum):
    """ISO-4217 fiat and common crypto currencies.

    Add new values here when needed; consumers should never hardcode a
    currency string anywhere else.
    """

    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"
    SGD = "SGD"
    HKD = "HKD"
    JPY = "JPY"
    AUD = "AUD"
    USDT = "USDT"
    USDC = "USDC"
    BTC = "BTC"
    ETH = "ETH"

    @property
    def is_fiat(self) -> bool:
        return self in _FIAT

    @property
    def is_crypto(self) -> bool:
        return self in _CRYPTO

    @property
    def decimals(self) -> int:
        """Canonical minor-unit precision for this currency."""
        return _DECIMALS[self]

    @classmethod
    def for_code(cls, code: str) -> Currency:
        """Look up a Currency by its ISO/ticker code.

        Raises ValueError with a clear message on unknown codes.
        """
        if not isinstance(code, str):
            raise ValueError(f"Currency.for_code expects a string, got {type(code).__name__}")
        key = code.strip().upper()
        try:
            return cls(key)
        except ValueError as e:
            raise ValueError(
                f"Unknown currency code {code!r}. Known: {', '.join(sorted(m.value for m in cls))}"
            ) from e


_FIAT: frozenset[Currency] = frozenset(
    {
        Currency.INR,
        Currency.USD,
        Currency.EUR,
        Currency.GBP,
        Currency.CHF,
        Currency.SGD,
        Currency.HKD,
        Currency.JPY,
        Currency.AUD,
    }
)

_CRYPTO: frozenset[Currency] = frozenset(
    {Currency.USDT, Currency.USDC, Currency.BTC, Currency.ETH}
)

_DECIMALS: dict[Currency, int] = {
    Currency.INR: 2,
    Currency.USD: 2,
    Currency.EUR: 2,
    Currency.GBP: 2,
    Currency.CHF: 2,
    Currency.SGD: 2,
    Currency.HKD: 2,
    Currency.JPY: 0,   # yen has no minor unit in practice
    Currency.AUD: 2,
    Currency.USDT: 6,
    Currency.USDC: 6,
    Currency.BTC: 8,
    Currency.ETH: 18,
}


class CurrencyAmount(BaseModel):
    """A precise monetary amount paired with its currency.

    Reject float construction at the field boundary. Arithmetic between
    two CurrencyAmounts requires matching currency; otherwise raises
    ValueError (not DomainError — this is a type-level mistake, not a
    capability issue).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal
    currency: Currency

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError(
                "CurrencyAmount.amount rejects float input to prevent binary "
                "floating-point rounding. Pass Decimal, int, or str."
            )
        return v

    @model_validator(mode="after")
    def _coerce_decimal(self) -> CurrencyAmount:
        # Let Decimal(str) handle int/str uniformly. After pydantic has
        # run its coercion, `self.amount` is already a Decimal.
        return self

    def __add__(self, other: CurrencyAmount) -> CurrencyAmount:
        self._require_same_currency(other, "add")
        return CurrencyAmount(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: CurrencyAmount) -> CurrencyAmount:
        self._require_same_currency(other, "subtract")
        return CurrencyAmount(amount=self.amount - other.amount, currency=self.currency)

    def _require_same_currency(self, other: CurrencyAmount, op: str) -> None:
        if not isinstance(other, CurrencyAmount):
            raise TypeError(
                f"Cannot {op} CurrencyAmount and {type(other).__name__}"
            )
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot {op} amounts in different currencies: "
                f"{self.currency.value} vs {other.currency.value}"
            )


__all__ = ["Currency", "CurrencyAmount"]
