from datetime import date

import pytest

from app.domain.services.date_validator import parse_invoice_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-05-13", date(2026, 5, 13)),
        ("13/05/2026", date(2026, 5, 13)),
        ("13-05-2026", date(2026, 5, 13)),
        ("13.05.2026", date(2026, 5, 13)),
    ],
)
def test_parse_invoice_date(raw: str, expected: date) -> None:
    assert parse_invoice_date(raw) == expected


def test_parse_invoice_date_rejects_invalid_dates() -> None:
    with pytest.raises(ValueError):
        parse_invoice_date("31/02/2026")
