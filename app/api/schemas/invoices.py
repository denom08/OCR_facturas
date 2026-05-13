from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    text: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    source: Literal["xml", "digital_text", "ocr", "layout", "vlm", "dummy"]


class Party(BaseModel):
    legal_name: str
    tax_id: str


class InvoiceData(BaseModel):
    number: str
    issue_date: date
    due_date: date | None = None


class TaxLine(BaseModel):
    tax_rate: Decimal
    tax_base: Decimal
    tax_amount: Decimal


class Totals(BaseModel):
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    advance_amount: Decimal | None = None
    withholding_amount: Decimal | None = None


class ConfidenceReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_score: float = Field(alias="global", ge=0, le=1)
    fields: dict[str, float] = Field(default_factory=dict)
    needs_review: list[str] = Field(default_factory=list)


class Invoice(BaseModel):
    supplier: Party
    customer: Party
    invoice_data: InvoiceData
    tax_lines: list[TaxLine]
    totals: Totals


class ApiError(BaseModel):
    code: str
    message: str
    field: str | None = None


class InvoiceResponse(BaseModel):
    status: Literal["ok", "error"]
    invoice: Invoice | None
    confidence: ConfidenceReport
    warnings: list[str] = Field(default_factory=list)
    errors: list[ApiError] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    debug: dict[str, Any] | None = None


def build_dummy_invoice_response(
    *, include_evidence: bool = True, include_debug: bool = False
) -> InvoiceResponse:
    """Construye una respuesta dummy válida para fijar el contrato API inicial."""
    evidence = {
        "invoice_data.number": Evidence(
            text="DUMMY-0001",
            page=1,
            bbox=None,
            source="dummy",
        )
    }

    return InvoiceResponse(
        status="ok",
        invoice=Invoice(
            supplier=Party(legal_name="Proveedor Dummy S.L.", tax_id="00000000T"),
            customer=Party(legal_name="Cliente Dummy S.L.", tax_id="00000001R"),
            invoice_data=InvoiceData(number="DUMMY-0001", issue_date=date(2000, 1, 1)),
            tax_lines=[
                TaxLine(
                    tax_rate=Decimal("21.00"),
                    tax_base=Decimal("100.00"),
                    tax_amount=Decimal("21.00"),
                )
            ],
            totals=Totals(
                net_amount=Decimal("100.00"),
                tax_amount=Decimal("21.00"),
                gross_amount=Decimal("121.00"),
            ),
        ),
        confidence=ConfidenceReport(
            global_score=0.0,
            fields={
                "supplier.legal_name": 0.0,
                "supplier.tax_id": 0.0,
                "customer.legal_name": 0.0,
                "customer.tax_id": 0.0,
                "invoice_data.number": 0.0,
                "invoice_data.issue_date": 0.0,
                "tax_lines": 0.0,
                "totals": 0.0,
            },
            needs_review=[
                "supplier.legal_name",
                "supplier.tax_id",
                "customer.legal_name",
                "customer.tax_id",
                "invoice_data.number",
                "invoice_data.issue_date",
                "tax_lines",
                "totals",
            ],
        ),
        warnings=["Respuesta dummy: extracción real todavía no implementada."],
        errors=[],
        evidence=evidence if include_evidence else {},
        debug={"stage": "dummy_contract"} if include_debug else None,
    )
