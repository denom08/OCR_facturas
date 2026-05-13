from decimal import Decimal

import pytest

from app.shared.money import normalize_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56 €", Decimal("1234.56")),
        ("1234,5", Decimal("1234.50")),
        ("1,234.56", Decimal("1234.56")),
        (42, Decimal("42.00")),
        (Decimal("10.005"), Decimal("10.01")),
    ],
)
def test_normalize_money(raw: Decimal | int | str, expected: Decimal) -> None:
    assert normalize_money(raw) == expected


def test_normalize_money_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_money("no es dinero")
