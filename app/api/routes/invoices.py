"""Rutas FastAPI para extracción de facturas."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.schemas.invoices import InvoiceResponse
from app.application.pipeline.digital_pipeline import process_digital_invoice
from app.infrastructure.pdf.pymupdf_reader import PyMuPdfReader

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


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

    # Usar el pipeline digital
    reader = PyMuPdfReader()
    return process_digital_invoice(
        pdf_reader=reader,
        pdf_source=pdf_source,
        include_evidence=include_evidence,
        include_debug=include_debug or force_ocr,
    )