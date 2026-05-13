"""Rutas FastAPI para extracción de facturas."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.schemas.invoices import InvoiceResponse
from app.application.pipeline.digital_pipeline import process_digital_invoice
from app.application.pipeline.ocr_pipeline import process_scanned_invoice
from app.application.pipeline.xml_pipeline import process_xml_invoice
from app.application.ports.ocr_engine import OcrEngine
from app.application.ports.pdf_reader import PdfKind
from app.infrastructure.ocr import PaddleOcrEngine
from app.infrastructure.pdf import PyMuPdfReader
from app.infrastructure.xml import FacturaeParser, PyMuPdfEmbeddedXmlExtractor

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])

# Singleton extractors and parsers
_xml_extractor = PyMuPdfEmbeddedXmlExtractor()
_facturae_parser = FacturaeParser()
_ocr_engine: OcrEngine | None = None  # Lazy init


def _get_ocr_engine() -> OcrEngine:
    """Lazy initialization del motor OCR."""
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = PaddleOcrEngine()
    return _ocr_engine


@router.post("/extract", response_model=InvoiceResponse, response_model_by_alias=True)
async def extract_invoice(
    file: Annotated[UploadFile, File(description="Factura PDF a procesar.")],
    force_ocr: Annotated[bool, Form()] = False,
    include_evidence: Annotated[bool, Form()] = True,
    include_debug: Annotated[bool, Form()] = False,
) -> InvoiceResponse:
    """Recibe una factura PDF y devuelve una respuesta estructurada."""
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_file_type",
                "message": "El archivo debe ser un PDF.",
                "field": "file",
            },
        )

    # Leer el contenido del PDF
    content = await file.read()
    pdf_source = BytesIO(content)

    # Clasificar para decidir el pipeline
    reader = PyMuPdfReader()
    kind = reader.classify(pdf_source)
    pdf_source.seek(0)

    # Si tiene XML embebido, priorizar pipeline XML
    if kind == PdfKind.EMBEDDED_XML:
        return process_xml_invoice(
            xml_extractor=_xml_extractor,
            pdf_source=pdf_source,
            parsers=[_facturae_parser],
            include_evidence=include_evidence,
            include_debug=include_debug or force_ocr,
        )

    # Si es escaneado/híbrido o se fuerza OCR, usar pipeline OCR
    if force_ocr or kind in (PdfKind.SCANNED, PdfKind.HYBRID):
        return process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf_source,
            ocr_engine=_get_ocr_engine(),
            force_ocr=force_ocr,
            include_evidence=include_evidence,
            include_debug=include_debug,
        )

    # Otherwise use digital pipeline
    return process_digital_invoice(
        pdf_reader=reader,
        pdf_source=pdf_source,
        include_evidence=include_evidence,
        include_debug=include_debug or force_ocr,
    )