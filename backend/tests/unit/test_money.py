from decimal import Decimal

import pytest

from app.domain.enums import MoneyUnit
from app.domain.money import MoneyError, format_inr, parse_paise


def test_money_rejects_float_authority() -> None:
    """Changing the float guard would silently admit binary rounding into financial truth."""
    with pytest.raises(MoneyError, match="floats are not allowed"):
        parse_paise(47.5, MoneyUnit.PAISE)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("4750.00", MoneyUnit.RUPEES, 475_000),
        ("-250.50", MoneyUnit.RUPEES, -25_050),
        (Decimal("475000"), MoneyUnit.PAISE, 475_000),
        (475000, MoneyUnit.PAISE, 475_000),
    ],
)
def test_money_converts_to_exact_whole_paise(value: object, unit: MoneyUnit, expected: int) -> None:
    """A wrong multiplier or sign conversion would change authoritative settlement totals."""
    assert parse_paise(value, unit) == expected


def test_money_rejects_fractional_paise() -> None:
    """Rounding fractional paise would invent or discard money."""
    with pytest.raises(MoneyError, match="whole paise"):
        parse_paise("10.25", MoneyUnit.PAISE)


def test_inr_formatter_uses_indian_grouping_and_sign() -> None:
    """Incorrect grouping or sign display would mislead a finance operator."""
    assert format_inr(84_239_100) == "₹8,42,391.00"
    assert format_inr(-25_050) == "-₹250.50"

