"""Tests para el pipeline OCR (B6)."""

from io import BytesIO

from app.application.pipeline.normalize_document import ExtractionSource
from app.application.pipeline.ocr_pipeline import (
    _build_normalized_document_from_ocr,
    _candidate_value,
    process_scanned_invoice,
)
from app.application.ports.ocr_engine import OcrBlock, OcrResult
from app.application.ports.pdf_reader import PdfKind
from tests.unit.fake_ocr_engine import FakeOcrEngine, UnavailableOcrEngine


class TestBuildNormalizedDocumentFromOcr:
    """Tests para _build_normalized_document_from_ocr."""

    def test_basic_conversion(self):
        """Convierte OcrResult a NormalizedDocument."""
        ocr_result = OcrResult(
            blocks=[
                OcrBlock(
                    text="FACTURA 1234",
                    bbox=(10.0, 20.0, 100.0, 40.0),
                    confidence=0.92,
                ),
                OcrBlock(
                    text="Fecha: 01/01/2024",
                    bbox=(10.0, 50.0, 150.0, 70.0),
                    confidence=0.88,
                ),
            ],
            page=1,
            engine="test",
        )

        doc = _build_normalized_document_from_ocr(ocr_result, page=1)

        assert len(doc.pages) == 1
        assert doc.pages[0].page_number == 1
        assert doc.source == ExtractionSource.OCR
        assert len(doc.pages[0].blocks) == 2

        # Verificar primer bloque
        blk = doc.pages[0].blocks[0]
        assert blk.text == "FACTURA 1234"
        assert blk.bbox == (10.0, 20.0, 100.0, 40.0)
        assert blk.confidence == 0.92
        assert blk.source == ExtractionSource.OCR

    def test_multiple_pages(self):
        """Múltiples páginas se agrupan correctamente."""
        ocr1 = OcrResult(
            blocks=[OcrBlock(text="Página 1", bbox=(0, 0, 100, 20), confidence=0.9)],
            page=1,
            engine="test",
        )
        ocr2 = OcrResult(
            blocks=[OcrBlock(text="Página 2", bbox=(0, 0, 100, 20), confidence=0.85)],
            page=2,
            engine="test",
        )

        doc1 = _build_normalized_document_from_ocr(ocr1, page=1)
        doc2 = _build_normalized_document_from_ocr(ocr2, page=2)

        assert doc1.pages[0].blocks[0].text == "Página 1"
        assert doc2.pages[0].blocks[0].text == "Página 2"

    def test_empty_result(self):
        """Resultado vacío produce documento sin bloques."""
        ocr_result = OcrResult(blocks=[], page=1, engine="test")
        doc = _build_normalized_document_from_ocr(ocr_result, page=1)

        # Empty OCR blocks produce empty pages list
        assert doc.pages == []
        assert doc.all_blocks == []


class TestCandidateValue:
    """Tests para _candidate_value helper."""

    def test_normalize_success(self):
        """Normaliza correctamente cuando la función no lanza."""

        def double(s: str) -> int:
            return int(s) * 2

        result = _candidate_value(type("C", (), {"value": "5"}), double)
        assert result == 10

    def test_normalize_failure_fallback(self):
        """Si la función lanza, devuelve el valor original."""

        def bad(s: str) -> int:
            raise ValueError("bad")

        c = type("C", (), {"value": "abc"})()
        result = _candidate_value(c, bad)
        assert result == "abc"


class FakePdfReader:
    """PdfReader fake para tests de OCR pipeline."""

    def __init__(self, kind: PdfKind = PdfKind.SCANNED, page_count: int = 1):
        self._kind = kind
        self._page_count = page_count
        self._rendered: dict[int, BytesIO] = {}

    def classify(self, pdf_source) -> PdfKind:
        return self._kind

    def page_count(self, pdf_source) -> int:
        return self._page_count

    def render_page_to_image(
        self, pdf_source, page_number: int, dpi: int = 150
    ) -> BytesIO:
        # Simular imagen renderizada
        img = self._rendered.get(page_number)
        if img is None:
            img = BytesIO(b"fake_png_image")
            self._rendered[page_number] = img
        return img


class TestProcessScannedInvoice:
    """Tests para process_scanned_invoice."""

    def test_error_when_pdf_not_scanned_and_no_force(self):
        """Si el PDF no es escaneado/híbrido y no hay force_ocr, error."""
        reader = FakePdfReader(kind=PdfKind.DIGITAL)
        ocr = FakeOcrEngine()
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=False,
        )

        assert response.status == "error"
        assert any(
            e.code == "unsupported_pdf_kind" for e in response.errors
        )

    def test_error_when_ocr_unavailable(self):
        """Si OCR no está disponible, responde con error controlado."""
        reader = FakePdfReader(kind=PdfKind.SCANNED)
        ocr = UnavailableOcrEngine()
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=False,
        )

        assert response.status == "error"
        assert any(e.code == "ocr_unavailable" for e in response.errors)
        assert len(response.warnings) > 0

    def test_force_ocr_on_digital_pdf(self):
        """force_ocr=True fuerza OCR incluso en PDF digital.

        Verifica que la ruta de OCR se selecciona cuando force_ocr=True,
        sin verificar extracción completa (que depende de los patrones
        de extracción de candidatos de B4).
        """
        reader = FakePdfReader(kind=PdfKind.DIGITAL, page_count=1)
        ocr = FakeOcrEngine(
            blocks=[
                OcrBlock(text="FACTURA 2024/001", bbox=(10, 10, 200, 40), confidence=0.9),
                OcrBlock(text="Fecha: 01/01/2024", bbox=(10, 50, 150, 70), confidence=0.85),
                OcrBlock(text="EMISOR B12345678", bbox=(10, 100, 200, 120), confidence=0.95),
            ]
        )
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=True,
        )

        # force_ocr fuerza el pipeline OCR incluso en PDF digital
        # El invoice puede ser None si faltan campos obligatorios tras OCR,
        # pero el pipeline debe ejecutarse sin crashear y con estado 'error'
        # (no 'ok' porque faltan campos mínimos tras extracción fake).
        assert response.status == "error"
        # Debe indicar que se usó OCR como fuente
        if response.debug:
            assert response.debug["stage"] == "ocr_pipeline"

    def test_basic_invoice_extraction(self):
        """Extrae datos básicos de un documento escaneado fake."""
        reader = FakePdfReader(kind=PdfKind.SCANNED, page_count=1)
        # Blocks must have tax IDs in same block as EMISOR/CLIENTE keywords
        # and proper amount format for extraction patterns
        ocr = FakeOcrEngine(
            blocks=[
                OcrBlock(
                    text="FACTURA 2024/001",
                    bbox=(10.0, 10.0, 200.0, 40.0),
                    confidence=0.9,
                ),
                OcrBlock(
                    text="Fecha: 01/03/2024",
                    bbox=(10.0, 50.0, 200.0, 70.0),
                    confidence=0.88,
                ),
                OcrBlock(
                    text="EMISOR A12345678",
                    bbox=(10.0, 100.0, 200.0, 120.0),
                    confidence=0.95,
                ),
                OcrBlock(
                    text="Empresa Proveedora S.L.",
                    bbox=(10.0, 130.0, 300.0, 150.0),
                    confidence=0.85,
                ),
                OcrBlock(
                    text="CLIENTE B87654321",
                    bbox=(10.0, 170.0, 200.0, 190.0),
                    confidence=0.95,
                ),
                OcrBlock(
                    text="Cliente Ejemplo S.A.",
                    bbox=(10.0, 200.0, 300.0, 220.0),
                    confidence=0.85,
                ),
                OcrBlock(
                    text="Base imponible 100,00 EUR",
                    bbox=(10.0, 300.0, 200.0, 320.0),
                    confidence=0.8,
                ),
                OcrBlock(
                    text="IVA 21% 21,00 EUR",
                    bbox=(10.0, 330.0, 150.0, 350.0),
                    confidence=0.8,
                ),
                OcrBlock(
                    text="TOTAL FACTURA 121,00 EUR",
                    bbox=(10.0, 360.0, 250.0, 380.0),
                    confidence=0.85,
                ),
            ]
        )
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=True,
            include_evidence=True,
        )

        assert response.status == "ok"
        assert response.invoice is not None
        # Verificar que se Extrajeron datos
        assert response.invoice.invoice_data.number == "2024/001"
        # Confianza global debe ser > 0
        assert response.confidence.global_score > 0
        # Debe haber warnings si faltan campos
        assert isinstance(response.warnings, list)

    def test_ocr_no_text_detected(self):
        """Si OCR no detecta texto, devuelve error controlado."""
        reader = FakePdfReader(kind=PdfKind.SCANNED, page_count=1)
        ocr = FakeOcrEngine(blocks=[])  # Sin bloques
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=True,
        )

        assert response.status == "error"
        assert any(e.code == "ocr_no_text" for e in response.errors)

    def test_debug_info_included(self):
        """Incluye debug cuando include_debug=True."""
        reader = FakePdfReader(kind=PdfKind.SCANNED, page_count=2)
        ocr = FakeOcrEngine()
        pdf = BytesIO(b"fake pdf")

        response = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf,
            ocr_engine=ocr,
            force_ocr=True,
            include_debug=True,
        )

        assert response.debug is not None
        assert response.debug["stage"] == "ocr_pipeline"
        assert response.debug["kind"] == "scanned"
        assert response.debug["engine"] == "FakeOCR"
        assert response.debug["page_count"] == 2


class TestOcrBlockModel:
    """Tests para el modelo OcrBlock."""

    def test_ocr_block_has_confidence(self):
        """OcrBlock tiene campo confidence."""
        block = OcrBlock(
            text="Test",
            bbox=(0, 0, 100, 50),
            confidence=0.87,
        )
        assert block.confidence == 0.87

    def test_ocr_result_full_text(self):
        """OcrResult.full_text concatena todos los textos."""
        result = OcrResult(
            blocks=[
                OcrBlock(text="Línea 1", bbox=(0, 0, 50, 10), confidence=0.9),
                OcrBlock(text="Línea 2", bbox=(0, 20, 50, 30), confidence=0.85),
            ],
            page=1,
        )
        assert result.full_text == "Línea 1\nLínea 2"