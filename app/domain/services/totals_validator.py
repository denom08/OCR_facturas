from dataclasses import dataclass
from decimal import Decimal

from app.domain.errors import DomainWarning
from app.shared.money import CENT


@dataclass(frozen=True)
class TaxLineAmounts:
    tax_rate: Decimal
    tax_base: Decimal
    tax_amount: Decimal


@dataclass(frozen=True)
class InvoiceTotals:
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    advance_amount: Decimal | None = None
    withholding_amount: Decimal | None = None


def validate_totals(
    tax_lines: list[TaxLineAmounts],
    totals: InvoiceTotals,
    *,
    tolerance: Decimal = CENT,
) -> list[DomainWarning]:
    """Valida coherencia de bases, IVA, adelantos, retenciones y total."""
    warnings: list[DomainWarning] = []

    expected_net = sum((line.tax_base for line in tax_lines), Decimal("0.00"))
    expected_tax = sum((line.tax_amount for line in tax_lines), Decimal("0.00"))

    if _differs(expected_net, totals.net_amount, tolerance):
        warnings.append(
            DomainWarning(
                code="net_amount_mismatch",
                message="La base imponible total no coincide con la suma de bases fiscales.",
                field="totals.net_amount",
            )
        )

    if _differs(expected_tax, totals.tax_amount, tolerance):
        warnings.append(
            DomainWarning(
                code="tax_amount_mismatch",
                message="El IVA total no coincide con la suma de cuotas fiscales.",
                field="totals.tax_amount",
            )
        )

    for index, line in enumerate(tax_lines):
        expected_line_tax = line.tax_base * line.tax_rate / Decimal("100")
        if _differs(expected_line_tax, line.tax_amount, tolerance):
            warnings.append(
                DomainWarning(
                    code="tax_line_mismatch",
                    message="La cuota de IVA no coincide con base * porcentaje.",
                    field=f"tax_lines[{index}].tax_amount",
                )
            )

    advance = totals.advance_amount or Decimal("0.00")
    withholding = totals.withholding_amount or Decimal("0.00")
    expected_gross = totals.net_amount + totals.tax_amount - advance - withholding

    if _differs(expected_gross, totals.gross_amount, tolerance):
        warnings.append(
            DomainWarning(
                code="gross_amount_mismatch",
                message="El total factura no cuadra con base + IVA - adelantos - retenciones.",
                field="totals.gross_amount",
            )
        )

    return warnings


def _differs(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) > tolerance
