"""Tests para el pipeline VLM (B9)."""



from app.api.schemas.invoices import (
    ApiError,
    ConfidenceReport,
    Invoice,
    InvoiceData,
    InvoiceResponse,
    Party,
    TaxLine,
    Totals,
)
from app.application.pipeline.extract_candidates import Candidate
from app.application.pipeline.normalize_document import (
    ExtractionSource,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
)
from app.infrastructure.vlm.vlm_pipeline import (
    _build_vlm_evidence,
    _vlm_candidates_to_invoice,
    invoke_vlm_if_needed,
)
from tests.unit.fake_vlm_extractor import FakeVlmExtractor, UnavailableVlmExtractor


class TestVlmCandidatesToInvoice:
    """Tests para _vlm_candidates_to_invoice."""

    def test_builds_invoice_from_valid_candidates(self):
        """Construye Invoice válido desde candidatos VLM."""
        # Usar tax_ids que pasan la validación B2
        # NIF válido: 00000000T (número 0, letra T)
        # CIF válido: P1234567B (letra P, dígito control 7, ends in B)
        candidates = [
            Candidate(
                field_name="invoice_data.number",
                value="2024/001",
                normalized_value="2024/001",
                confidence=0.95,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="invoice_data.issue_date",
                value="2024-01-15",
                normalized_value="2024-01-15",
                confidence=0.95,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="supplier.tax_id",
                value="P1234567D",
                normalized_value="P1234567D",
                confidence=0.95,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="supplier.legal_name",
                value="Acme S.L.",
                normalized_value="Acme S.L.",
                confidence=0.9,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="customer.tax_id",
                value="00000000T",
                normalized_value="00000000T",
                confidence=0.95,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="customer.legal_name",
                value="Cliente S.A.",
                normalized_value="Cliente S.A.",
                confidence=0.9,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="tax_lines[21].tax_base",
                value="100.00",
                confidence=0.85,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="tax_lines[21].tax_amount",
                value="21.00",
                confidence=0.85,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="totals.net_amount",
                value="100.00",
                confidence=0.85,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="totals.tax_amount",
                value="21.00",
                confidence=0.85,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="totals.gross_amount",
                value="121.00",
                confidence=0.85,
                block=None,
                page=1,
            ),
        ]

        invoice, warnings, errors = _vlm_candidates_to_invoice(candidates, page=1)

        assert invoice is not None
        assert invoice.invoice_data.number == "2024/001"
        assert invoice.supplier.tax_id == "P1234567D"
        assert invoice.customer.tax_id == "00000000T"
        assert len(invoice.tax_lines) >= 1
        assert len(warnings) == 0
        assert len(errors) == 0

    def test_returns_error_for_missing_number(self):
        """Devuelve error si falta número de factura."""
        candidates = [
            Candidate(
                field_name="invoice_data.issue_date",
                value="2024-01-15",
                confidence=0.95,
                block=None,
                page=1,
            ),
        ]

        invoice, warnings, errors = _vlm_candidates_to_invoice(candidates)

        assert invoice is None
        assert any(e.code == "missing_field" and "number" in e.field for e in errors)

    def test_returns_error_for_missing_date(self):
        """Devuelve error si falta fecha."""
        candidates = [
            Candidate(
                field_name="invoice_data.number",
                value="2024/001",
                confidence=0.95,
                block=None,
                page=1,
            ),
        ]

        invoice, warnings, errors = _vlm_candidates_to_invoice(candidates)

        assert invoice is None
        assert any(e.code == "missing_field" and "issue_date" in e.field for e in errors)


class TestBuildVlmEvidence:
    """Tests para _build_vlm_evidence."""

    def test_builds_evidence_from_candidates(self):
        """Construye mapa de evidencias desde candidatos."""
        candidates = [
            Candidate(
                field_name="invoice_data.number",
                value="2024/001",
                confidence=0.95,
                block=None,
                page=1,
            ),
            Candidate(
                field_name="supplier.tax_id",
                value="B12345678",
                confidence=0.95,
                block=None,
                page=1,
            ),
        ]

        evidence = _build_vlm_evidence(candidates)

        assert "invoice_data.number" in evidence
        assert evidence["invoice_data.number"].text == "2024/001"
        assert evidence["invoice_data.number"].source == "vlm"
        assert evidence["invoice_data.number"].page == 1

    def test_empty_for_no_candidates(self):
        """Devuelve dict vacío si no hay candidatos."""
        evidence = _build_vlm_evidence([])
        assert evidence == {}


class TestInvokeVlmIfNeeded:
    """Tests para invoke_vlm_if_needed."""

    def test_no_invoke_when_extractor_unavailable(self):
        """No se invoca VLM si el extractor no está disponible."""
        response = InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[],
            errors=[
                ApiError(code="missing_field", message="Falta número", field="invoice_data.number")
            ],
        )

        result = invoke_vlm_if_needed(
            invoice_response=response,
            vlm_extractor=UnavailableVlmExtractor(),
        )

        assert result is response
        assert any("no disponible" in w for w in result.warnings)

    def test_no_invoke_when_fields_resolved(self):
        """No se invoca VLM si ya están todos los campos resueltos."""
        response = InvoiceResponse(
            status="ok",
            invoice=Invoice(
                supplier=Party(legal_name="Acme", tax_id="B12345678"),
                customer=Party(legal_name="Cliente", tax_id="A87654321"),
                invoice_data=InvoiceData(number="2024/001", issue_date="2024-01-15"),
                tax_lines=[TaxLine(tax_rate="21", tax_base="100.00", tax_amount="21.00")],
                totals=Totals(net_amount="100.00", tax_amount="21.00", gross_amount="121.00"),
            ),
            confidence=ConfidenceReport(global_score=0.85, fields={"invoice_data.number": 0.85}),
        )

        extractor = FakeVlmExtractor()
        result = invoke_vlm_if_needed(
            invoice_response=response,
            vlm_extractor=extractor,
            normalized_document=None,
        )

        # No se ejecutó el extractor porque no hizo falta
        # La respuesta se retorna sin cambios
        assert result.status == "ok"

    def test_invoke_on_missing_critical_fields(self):
        """Se invoca VLM cuando faltan campos obligatorios."""
        response = InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[],
            errors=[
                ApiError(code="missing_field", message="Falta número", field="invoice_data.number")
            ],
        )

        extractor = FakeVlmExtractor()
        result = invoke_vlm_if_needed(
            invoice_response=response,
            vlm_extractor=extractor,
            normalized_document=_make_fake_normalized_doc(),
            include_debug=True,
        )

        # El VLM fue invocado. Verificamos por debug info.
        assert result.debug is not None
        assert result.debug["vlm_triggered"] is True

    def test_invoke_on_low_confidence(self):
        """Se invoca VLM cuando la confianza global es baja."""
        response = InvoiceResponse(
            status="ok",
            invoice=Invoice(
                supplier=Party(legal_name="Acme", tax_id="P1234567D"),
                customer=Party(legal_name="Cliente", tax_id="00000000T"),
                invoice_data=InvoiceData(number="2024/001", issue_date="2024-01-15"),
                tax_lines=[TaxLine(tax_rate="21", tax_base="100.00", tax_amount="21.00")],
                totals=Totals(net_amount="100.00", tax_amount="21.00", gross_amount="121.00"),
            ),
            confidence=ConfidenceReport(
                global_score=0.4,
                fields={"invoice_data.number": 0.4, "supplier.tax_id": 0.4},
            ),
        )

        extractor = FakeVlmExtractor()
        result = invoke_vlm_if_needed(
            invoice_response=response,
            vlm_extractor=extractor,
            normalized_document=_make_fake_normalized_doc(),
            include_debug=True,
        )

        # El VLM fue invocado. Verificamos por debug info.
        assert result.debug is not None
        assert result.debug["vlm_triggered"] is True

    def test_debug_included_when_requested(self):
        """Incluye debug info cuando include_debug=True."""
        response = InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[],
            errors=[
                ApiError(code="missing_field", message="Falta número", field="invoice_data.number")
            ],
        )

        extractor = FakeVlmExtractor()
        result = invoke_vlm_if_needed(
            invoice_response=response,
            vlm_extractor=extractor,
            normalized_document=_make_fake_normalized_doc(),
            include_debug=True,
        )

        assert result.debug is not None
        assert result.debug["stage"] == "vlm_fallback"
        assert result.debug["vlm_triggered"] is True


def _make_fake_normalized_doc() -> NormalizedDocument:
    """Crea un NormalizedDocument fake para tests."""
    return NormalizedDocument(
        pages=[
            NormalizedPage(
                page_number=1,
                blocks=[
                    NormalizedBlock(
                        text="FACTURA 2024/001",
                        bbox=(10.0, 10.0, 200.0, 40.0),
                        page=1,
                        source=ExtractionSource.OCR,
                    )
                ],
            )
        ],
        source=ExtractionSource.OCR,
    )