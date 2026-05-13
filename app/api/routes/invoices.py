"""Rutas FastAPI para extracción de facturas."""

import logging
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
from app.shared.logging import (
    TimingCollector,
    generate_request_id,
    log_info,
    log_warning,
    set_request_id,
    stage_timer,
)

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])
logger = logging.getLogger("app.invoices")

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
    # Generar request_id y configurar contexto de logging
    request_id = generate_request_id()
    set_request_id(request_id)

    # Timing collector para todo el pipeline
    timing = TimingCollector()
    timing.start()

    log_info(
        "request_started",
        filename=getattr(file, "filename", "unknown"),
        force_ocr=force_ocr,
        include_debug=include_debug,
    )

    if file.content_type != "application/pdf":
        timing.add_stage("validate_input", 0.0, reason="not_pdf")
        log_warning("request_invalid_file_type", content_type=file.content_type)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_file_type",
                "message": "El archivo debe ser un PDF.",
                "field": "file",
                "request_id": request_id,
            },
        )

    # Leer el contenido del PDF
    content = await file.read()
    pdf_source = BytesIO(content)

    # Clasificar para decidir el pipeline
    with stage_timer(timing, "pdf_classify"):
        reader = PyMuPdfReader()
        kind = reader.classify(pdf_source)
        pdf_source.seek(0)

    log_info("pdf_classified", kind=kind.value, request_id=request_id)

    # Si tiene XML embebido, priorizar pipeline XML
    if kind == PdfKind.EMBEDDED_XML:
        log_info("pipeline_selected", pipeline="xml", request_id=request_id)
        result = process_xml_invoice(
            xml_extractor=_xml_extractor,
            pdf_source=pdf_source,
            parsers=[_facturae_parser],
            include_evidence=include_evidence,
            include_debug=include_debug or force_ocr,
        )
    # Si es escaneado/híbrido o se fuerza OCR, usar pipeline OCR
    elif force_ocr or kind in (PdfKind.SCANNED, PdfKind.HYBRID):
        log_info("pipeline_selected", pipeline="ocr", kind=kind.value, request_id=request_id)
        result = process_scanned_invoice(
            pdf_reader=reader,
            pdf_source=pdf_source,
            ocr_engine=_get_ocr_engine(),
            force_ocr=force_ocr,
            include_evidence=include_evidence,
            include_debug=include_debug,
        )
    # Otherwise use digital pipeline
    else:
        log_info("pipeline_selected", pipeline="digital", kind=kind.value, request_id=request_id)
        result = process_digital_invoice(
            pdf_reader=reader,
            pdf_source=pdf_source,
            include_evidence=include_evidence,
            include_debug=include_debug or force_ocr,
        )

    # Adjuntar request_id y timings al debug si está activo
    if result.debug is not None and isinstance(result.debug, dict):
        result.debug["request_id"] = request_id
        result.debug["timings"] = timing.to_dict()
    elif include_debug:
        # Debug activo pero los pipelines no lo incluyeron — construirlo aquí
        result.debug = {
            "request_id": request_id,
            "stage": "unknown",
            "timings": timing.to_dict(),
            "warnings_count": len(result.warnings),
            "errors_count": len(result.errors),
        }

    log_info(
        "request_completed",
        request_id=request_id,
        status=result.status,
        global_score=result.confidence.global_score,
        warnings=len(result.warnings),
        errors=len(result.errors),
        debug=include_debug,
    )

    return result