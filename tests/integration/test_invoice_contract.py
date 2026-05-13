"""Integration tests for the invoice extraction API."""

from io import BytesIO

import fitz
from fastapi.testclient import TestClient

from app.api.main import app


def _synthetic_digital_invoice() -> bytes:
    """Creates a minimal valid PDF with extractable text.

    Uses text blocks that the pattern extractor can reliably parse.
    """
    doc = fitz.open()

    # Page 1: invoice header with number and date
    page1 = doc.new_page()
    page1.insert_text(
        (50, 50),
        "FACTURA NUM. 2024/001\n"
        "FECHA: 15/01/2024\n",
        fontname="helv",
    )

    # Page 2: parties
    page2 = doc.new_page()
    page2.insert_text(
        (50, 50),
        "EMISOR: Vendedor Demo S.L.\n"
        "NIF/CIF: B64723812\n",
        fontname="helv",
    )
    page2.insert_text(
        (50, 80),
        "CLIENTE: Comprador Test S.A.\n"
        "NIF/CIF: A58818501\n",
        fontname="helv",
    )

    # Page 3: tax lines and totals
    page3 = doc.new_page()
    page3.insert_text(
        (50, 50),
        "BASE IMPONIBLE: 200,00 EUR\n"
        "IVA 21%: 42,00 EUR\n"
        "TOTAL FACTURA: 242,00 EUR\n",
        fontname="helv",
    )

    buf = BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestInvoiceContract:
    """API contract tests using synthetic PDFs."""

    def test_extract_digital_invoice_returns_valid_response(self) -> None:
        """End-to-end test: synthetic digital PDF -> structured JSON."""
        client = TestClient(app)

        response = client.post(
            "/api/v1/invoices/extract",
            files={
                "file": (
                    "invoice.pdf",
                    _synthetic_digital_invoice(),
                    "application/pdf",
                )
            },
            data={"include_evidence": "true", "include_debug": "true"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["invoice"] is not None

        # Check key extracted fields are present and non-empty
        invoice = payload["invoice"]
        assert invoice["invoice_data"]["number"] == "2024/001"
        assert invoice["invoice_data"]["issue_date"] == "2024-01-15"

        # Supplier and customer tax IDs
        assert invoice["supplier"]["tax_id"] == "B64723812"
        assert invoice["customer"]["tax_id"] == "A58818501"

        # Names detected (may be partial due to PDF text layout)
        assert invoice["supplier"]["legal_name"]
        assert invoice["customer"]["legal_name"]

        # Tax lines
        assert len(invoice["tax_lines"]) >= 1
        assert invoice["tax_lines"][0]["tax_rate"] in ("21", "21.0", "21.00")

        # Totals
        assert invoice["totals"]["gross_amount"] == "242.00"

        # Confidence reporting
        assert "confidence" in payload
        assert "global" in payload["confidence"] or "global_score" in str(
            payload["confidence"]
        )

        # Evidence
        assert "evidence" in payload
        assert len(payload["evidence"]) > 0

        # Debug info
        assert payload["debug"]["stage"] == "digital_pipeline"

    def test_extract_invoice_rejects_non_pdf_files(self) -> None:
        """The API rejects files that are not PDFs."""
        client = TestClient(app)

        response = client.post(
            "/api/v1/invoices/extract",
            files={"file": ("invoice.txt", b"not a pdf", "text/plain")},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_file_type"

    def test_extract_invoice_requires_mandatory_fields(self) -> None:
        """Missing mandatory fields return status=error."""
        client = TestClient(app)

        # Empty PDF (scanned type) — pipeline returns error
        doc = fitz.open()
        doc.new_page()
        buf = BytesIO()
        doc.save(buf)
        doc.close()

        response = client.post(
            "/api/v1/invoices/extract",
            files={"file": ("empty.pdf", buf.getvalue(), "application/pdf")},
        )

        # Empty PDF classifies as SCANNED — not supported by digital pipeline
        payload = response.json()
        assert payload["status"] == "error"
        assert payload["errors"] is not None
        assert len(payload["errors"]) > 0