from decimal import Decimal

from app.domain.services.totals_validator import InvoiceTotals, TaxLineAmounts, validate_totals


def test_validate_totals_accepts_consistent_invoice() -> None:
    warnings = validate_totals(
        tax_lines=[
            TaxLineAmounts(
                tax_rate=Decimal("21.00"),
                tax_base=Decimal("100.00"),
                tax_amount=Decimal("21.00"),
            ),
            TaxLineAmounts(
                tax_rate=Decimal("10.00"),
                tax_base=Decimal("50.00"),
                tax_amount=Decimal("5.00"),
            ),
        ],
        totals=InvoiceTotals(
            net_amount=Decimal("150.00"),
            tax_amount=Decimal("26.00"),
            gross_amount=Decimal("176.00"),
        ),
    )

    assert warnings == []


def test_validate_totals_warns_when_amounts_do_not_match() -> None:
    warnings = validate_totals(
        tax_lines=[
            TaxLineAmounts(
                tax_rate=Decimal("21.00"),
                tax_base=Decimal("100.00"),
                tax_amount=Decimal("20.00"),
            )
        ],
        totals=InvoiceTotals(
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("20.00"),
            gross_amount=Decimal("121.00"),
        ),
    )

    assert [warning.code for warning in warnings] == ["tax_line_mismatch", "gross_amount_mismatch"]


def test_validate_totals_supports_withholding_and_advance() -> None:
    warnings = validate_totals(
        tax_lines=[
            TaxLineAmounts(
                tax_rate=Decimal("21.00"),
                tax_base=Decimal("100.00"),
                tax_amount=Decimal("21.00"),
            )
        ],
        totals=InvoiceTotals(
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("21.00"),
            advance_amount=Decimal("10.00"),
            withholding_amount=Decimal("15.00"),
            gross_amount=Decimal("96.00"),
        ),
    )

    assert warnings == []
