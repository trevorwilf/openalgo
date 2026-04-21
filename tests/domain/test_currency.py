"""Currency enum + CurrencyAmount arithmetic and float-rejection."""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.currency import Currency, CurrencyAmount


def test_all_currency_members_present() -> None:
    expected = {"INR", "USD", "EUR", "GBP", "CHF", "SGD", "HKD", "JPY", "AUD",
                "USDT", "USDC", "BTC", "ETH"}
    assert {c.value for c in Currency} == expected


@pytest.mark.parametrize(
    "code,is_fiat,is_crypto",
    [
        (Currency.INR, True, False),
        (Currency.USD, True, False),
        (Currency.EUR, True, False),
        (Currency.JPY, True, False),
        (Currency.USDT, False, True),
        (Currency.USDC, False, True),
        (Currency.BTC, False, True),
        (Currency.ETH, False, True),
    ],
)
def test_fiat_vs_crypto_flags(code: Currency, is_fiat: bool, is_crypto: bool) -> None:
    assert code.is_fiat is is_fiat
    assert code.is_crypto is is_crypto


def test_decimals() -> None:
    assert Currency.INR.decimals == 2
    assert Currency.USD.decimals == 2
    assert Currency.JPY.decimals == 0
    assert Currency.USDT.decimals == 6
    assert Currency.BTC.decimals == 8
    assert Currency.ETH.decimals == 18


def test_for_code_happy_path() -> None:
    assert Currency.for_code("usd") is Currency.USD
    assert Currency.for_code("  inr  ") is Currency.INR
    assert Currency.for_code("BTC") is Currency.BTC


def test_for_code_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown currency code"):
        Currency.for_code("XYZ")


def test_for_code_non_string_raises() -> None:
    with pytest.raises(ValueError, match="expects a string"):
        Currency.for_code(42)  # type: ignore[arg-type]


def test_currency_amount_constructs_from_decimal() -> None:
    amt = CurrencyAmount(amount=Decimal("100.50"), currency=Currency.USD)
    assert amt.amount == Decimal("100.50")
    assert amt.currency is Currency.USD


def test_currency_amount_accepts_int() -> None:
    amt = CurrencyAmount(amount=100, currency=Currency.INR)
    assert amt.amount == Decimal("100")


def test_currency_amount_accepts_str() -> None:
    amt = CurrencyAmount(amount="99.99", currency=Currency.EUR)
    assert amt.amount == Decimal("99.99")


def test_currency_amount_rejects_float() -> None:
    with pytest.raises(ValueError, match="rejects float"):
        CurrencyAmount(amount=100.5, currency=Currency.USD)  # type: ignore[arg-type]


def test_currency_amount_addition() -> None:
    a = CurrencyAmount(amount=Decimal("10.00"), currency=Currency.USD)
    b = CurrencyAmount(amount=Decimal("2.50"), currency=Currency.USD)
    total = a + b
    assert total.amount == Decimal("12.50")
    assert total.currency is Currency.USD


def test_currency_amount_subtraction() -> None:
    a = CurrencyAmount(amount=Decimal("10.00"), currency=Currency.USD)
    b = CurrencyAmount(amount=Decimal("2.50"), currency=Currency.USD)
    diff = a - b
    assert diff.amount == Decimal("7.50")


def test_currency_amount_mismatched_currency_add_raises() -> None:
    a = CurrencyAmount(amount=Decimal("10"), currency=Currency.USD)
    b = CurrencyAmount(amount=Decimal("10"), currency=Currency.INR)
    with pytest.raises(ValueError, match="Cannot add amounts in different currencies"):
        _ = a + b


def test_currency_amount_mismatched_currency_sub_raises() -> None:
    a = CurrencyAmount(amount=Decimal("10"), currency=Currency.USD)
    b = CurrencyAmount(amount=Decimal("10"), currency=Currency.INR)
    with pytest.raises(ValueError, match="Cannot subtract amounts in different currencies"):
        _ = a - b


def test_currency_amount_add_wrong_type_raises() -> None:
    a = CurrencyAmount(amount=Decimal("10"), currency=Currency.USD)
    with pytest.raises(TypeError, match="Cannot add"):
        _ = a + 5  # type: ignore[operator]


def test_currency_amount_sub_wrong_type_raises() -> None:
    a = CurrencyAmount(amount=Decimal("10"), currency=Currency.USD)
    with pytest.raises(TypeError, match="Cannot subtract"):
        _ = a - "oops"  # type: ignore[operator]


def test_currency_amount_is_frozen() -> None:
    a = CurrencyAmount(amount=Decimal("1"), currency=Currency.USD)
    with pytest.raises(Exception):  # pydantic raises ValidationError on assignment
        a.amount = Decimal("2")  # type: ignore[misc]
