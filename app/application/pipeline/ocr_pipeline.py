"""Pipeline de extracción para PDFs escaneados o híbridos sin texto extraíble.

Este pipeline:
1. Clasifica el PDF como SCANNED o HYBRID
2. Renderiza cada página a imagen (reutilizando B3 PdfReader.render_page_to_image)
3. Ejecuta OCR (PaddleOCR) sobre las imágenes
4. Normaliza la salida OCR a NormalizedDocument con ExtractionSource.OCR
5. Reutiliza los extractores de candidatos de B4 sobre el texto OCR
6. Genera InvoiceResponse con confianza, evidencias y warnings

Si el motor OCR no está disponible, responde con status=error + warning controlado
en lugar de crashear, cumpliendo el requisito de tolerancia a dependencias opcionales.
"""

import logging
from decimal import Decimal
from io import BytesIO

from app.api.schemas.invoices import (
    ApiError,
    ConfidenceReport,
    Evidence,
    Invoice,
    InvoiceData,
    InvoiceResponse,
    Party,
    TaxLine,
    Totals,
)
from app.application.pipeline.extract_candidates import (
    Candidate,
    extract_candidates,
)
from app.application.pipeline.normalize_document import (
    ExtractionSource,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
)
from app.application.ports.ocr_engine import OcrEngine, OcrUnavailableError
from app.application.ports.pdf_reader import PdfKind, PdfReader
from app.domain.services.date_validator import parse_invoice_date
from app.domain.services.tax_id_validator import is_valid_tax_id
from app.domain.services.totals_validator import (
    InvoiceTotals as DomainInvoiceTotals,
)
from app.domain.services.totals_validator import (
    TaxLineAmounts as DomainTaxLineAmounts,
)
from app.domain.services.totals_validator import (
    validate_totals,
)
from app.shared.logging import (
    TimingCollector,
    log_debug,
    log_warning,
    stage_timer,
)
from app.shared.money import normalize_money

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Construcción del documento normalizado desde OCR
# -------------------------------------------------------------------


def _build_normalized_document_from_ocr(
    ocr_result, page: int
) -> NormalizedDocument:
    """Convierte OcrResult en NormalizedDocument."""

    normalized_blocks: list[NormalizedBlock] = []
    for blk in ocr_result.blocks:
        normalized_blocks.append(
            NormalizedBlock(
                text=blk.text,
                bbox=blk.bbox,
                page=page,
                source=ExtractionSource.OCR,
                confidence=blk.confidence,
            )
        )

    # Agrupar por página
    by_page: dict[int, list[NormalizedBlock]] = {}
    for nb in normalized_blocks:
        by_page.setdefault(nb.page, []).append(nb)

    pages = [
        NormalizedPage(page_number=pn, blocks=sorted(blks, key=lambda b: b.bbox[1]))
        for pn, blks in sorted(by_page.items())
    ]

    return NormalizedDocument(
        pages=pages, source=ExtractionSource.OCR
    )


def _ocr_pages(
    pdf_reader: PdfReader,
    pdf_source: BytesIO | str,
    ocr_engine: OcrEngine,
    dpi: int = 150,
) -> NormalizedDocument:
    """Renderiza páginas PDF y ejecuta OCR.

    Reutiliza PdfReader.render_page_to_image de B3 para el renderizado.
    """
    page_count = pdf_reader.page_count(pdf_source)

    all_pages: list[NormalizedPage] = []
    for page_num in range(1, page_count + 1):
        # Renderizar página a imagen (reutiliza B3)
        image_data = pdf_reader.render_page_to_image(pdf_source, page_num, dpi)

        # Ejecutar OCR
        try:
            ocr_result = ocr_engine.process_image(image_data, page=page_num)
        except OcrUnavailableError as exc:
            logger.warning("OCR no disponible en página %d: %s", page_num, exc)
            raise

        # Normalizar resultado OCR
        doc = _build_normalized_document_from_ocr(ocr_result, page_num)
        all_pages.extend(doc.pages)

    return NormalizedDocument(pages=all_pages, source=ExtractionSource.OCR)


# -------------------------------------------------------------------
# Helper: map candidato -> valor normalizado
# -------------------------------------------------------------------


def _candidate_value(c: Candidate, normalize_fn) -> object:
    """Intenta normalizar el valor del candidato con la función dada."""
    try:
        return normalize_fn(c.value)
    except Exception:
        return c.value


# -------------------------------------------------------------------
# Construcción de la respuesta
# -------------------------------------------------------------------


def _build_evidence(c: Candidate) -> Evidence:
    return Evidence(
        text=c.value,
        page=c.page,
        bbox=c.block.bbox if c.block else None,
        source="ocr",
    )


def _build_tax_line(rate: str, base: Decimal, amount: Decimal) -> TaxLine:
    return TaxLine(
        tax_rate=Decimal(rate),
        tax_base=base,
        tax_amount=amount,
    )


# -------------------------------------------------------------------
# Use case: procesar PDF escaneado
# -------------------------------------------------------------------


def process_scanned_invoice(
    pdf_reader: PdfReader,
    pdf_source: BytesIO | str,
    ocr_engine: OcrEngine,
    *,
    force_ocr: bool = False,
    include_evidence: bool = True,
    include_debug: bool = False,
    dpi: int = 150,
) -> InvoiceResponse:
    """Procesa un PDF escaneado con OCR y devuelve un InvoiceResponse.

    Args:
        pdf_reader: Lector PDF (PyMuPdfReader de B3).
        pdf_source: PDF en BytesIO o path.
        ocr_engine: Motor OCR (PaddleOcrEngine, etc.).
        force_ocr: Forzar OCR aunque el PDF tenga texto digital.
        include_evidence: Incluir evidencias en la respuesta.
        include_debug: Incluir información de debug.
        dpi: Resolución de renderizado para OCR (por defecto 150).

    Returns:
        InvoiceResponse con datos extraídos o respuesta de error controlada.

    Respuesta controlada cuando OCR no está disponible::

        status="error"
        errors=[ApiError(code="ocr_unavailable", ...)]
        warnings=["PaddleOCR no está instalado. Instala: pip install ocr-facturas[paddleocr]"]
    """
    # Timing collector para todo el pipeline
    timing = TimingCollector()
    timing.start()

    # 1. Clasificar — requerimos SCANNED o HYBRID, o force_ocr
    with stage_timer(timing, "pdf_classify"):
        kind = pdf_reader.classify(pdf_source)

    if not force_ocr and kind not in (PdfKind.SCANNED, PdfKind.HYBRID):
        log_warning(
            "ocr_pipeline_rejected",
            reason="unsupported_kind",
            kind=kind.value,
        )
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[],
            errors=[
                ApiError(
                    code="unsupported_pdf_kind",
                    message=(
                        f"El PDF es de tipo {kind.value}; "
                        "se esperaba escaneado o híbrido, o force_ocr=True."
                    ),
                    field="file",
                )
            ],
            evidence={},
            debug={"kind": kind.value} if include_debug else None,
        )

    # 2. Verificar que el motor OCR esté disponible
    if not ocr_engine.is_available():
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[
                "El motor OCR no está disponible. "
                "Instala con: pip install ocr-facturas[paddleocr]"
            ],
            errors=[
                ApiError(
                    code="ocr_unavailable",
                    message=(
                        "El motor OCR no está instalado o no puede inicializarse. "
                        "La extracción requiere PaddleOCR."
                    ),
                    field="file",
                )
            ],
            evidence={},
            debug={
                "stage": "ocr_pipeline",
                "kind": kind.value,
                "engine": ocr_engine.name(),
                "available": False,
            } if include_debug else None,
        )

    # 3. OCR de todas las páginas
    with stage_timer(timing, "ocr", engine=ocr_engine.name(), dpi=dpi):
        try:
            doc = _ocr_pages(pdf_reader, pdf_source, ocr_engine, dpi)
        except OcrUnavailableError:
            timing.add_stage("ocr", 0.0, error="ocr_unavailable")
            log_warning("ocr_unavailable", engine=ocr_engine.name())
            return InvoiceResponse(
                status="error",
                invoice=None,
                confidence=ConfidenceReport(global_score=0.0),
                warnings=[
                    "El motor OCR no está disponible durante el procesamiento."
                ],
                errors=[
                    ApiError(
                        code="ocr_unavailable",
                        message="Error al ejecutar OCR. Comprueba la instalación.",
                        field="file",
                    )
                ],
                evidence={},
                debug={
                    "stage": "ocr_pipeline",
                    "kind": kind.value,
                    "engine": ocr_engine.name(),
                    "timings": timing.to_dict(),
                } if include_debug else None,
            )

    if not doc.all_blocks:
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=["OCR no detectó texto en el documento."],
            errors=[
                ApiError(
                    code="ocr_no_text",
                    message="El OCR no detectó texto en el documento escaneado.",
                    field="file",
                )
            ],
            evidence={},
            debug={
                "stage": "ocr_pipeline",
                "kind": kind.value,
                "page_count": pdf_reader.page_count(pdf_source),
            } if include_debug else None,
        )

    # 4. Extraer candidatos usando los patrones de B4
    with stage_timer(timing, "extract_candidates"):
        candidates = extract_candidates(doc)

    # 5. Recoger mejores candidatos por campo (misma lógica que digital_pipeline)
    fields_to_resolve = [
        "invoice_data.number",
        "invoice_data.issue_date",
        "supplier.tax_id",
        "supplier.legal_name",
        "customer.tax_id",
        "customer.legal_name",
        "totals.net_amount",
        "totals.tax_amount",
        "totals.gross_amount",
    ]

    resolved: dict[str, Candidate] = {}
    for f in fields_to_resolve:
        best = candidates.best_for(f)
        if best:
            resolved[f] = best

    # 6. Construir campos con la misma lógica que digital_pipeline
    warnings: list[str] = []
    errors: list[ApiError] = []
    field_confidence: dict[str, float] = {}

    # --- Número de factura ---
    inv_num = ""
    if "invoice_data.number" in resolved:
        inv_num = resolved["invoice_data.number"].value.strip()
        field_confidence["invoice_data.number"] = (
            resolved["invoice_data.number"].confidence
        )
    else:
        warnings.append("Número de factura no encontrado.")
        field_confidence["invoice_data.number"] = 0.0

    # --- Fecha ---
    inv_date = None
    if "invoice_data.issue_date" in resolved:
        try:
            inv_date = parse_invoice_date(
                resolved["invoice_data.issue_date"].value
            )
            field_confidence["invoice_data.issue_date"] = (
                resolved["invoice_data.issue_date"].confidence
            )
        except ValueError as exc:
            warnings.append(f"Fecha inválida: {exc}")
            field_confidence["invoice_data.issue_date"] = 0.0
    else:
        warnings.append("Fecha no encontrada.")
        field_confidence["invoice_data.issue_date"] = 0.0
        errors.append(
            ApiError(
                code="missing_field",
                message="Fecha no encontrada.",
                field="invoice_data.issue_date",
            )
        )

    # --- Supplier tax_id ---
    sup_tax_id = ""
    if "supplier.tax_id" in resolved:
        sup_tax_id = (
            resolved["supplier.tax_id"].normalized_value
            or resolved["supplier.tax_id"].value
        )
        field_confidence["supplier.tax_id"] = (
            resolved["supplier.tax_id"].confidence
        )
        if not is_valid_tax_id(sup_tax_id):
            warnings.append(
                f"CIF/NIF del emisor potencialmente inválido: {sup_tax_id}"
            )
            field_confidence["supplier.tax_id"] *= 0.5
    else:
        warnings.append("CIF/NIF del emisor no encontrado.")
        field_confidence["supplier.tax_id"] = 0.0

    # --- Supplier legal_name ---
    sup_name = ""
    if "supplier.legal_name" in resolved:
        sup_name = resolved["supplier.legal_name"].value.strip()
        field_confidence["supplier.legal_name"] = (
            resolved["supplier.legal_name"].confidence
        )
    else:
        warnings.append("Razón social del emisor no encontrada.")
        field_confidence["supplier.legal_name"] = 0.0

    # --- Customer tax_id ---
    cust_tax_id = ""
    if "customer.tax_id" in resolved:
        cust_tax_id = (
            resolved["customer.tax_id"].normalized_value
            or resolved["customer.tax_id"].value
        )
        field_confidence["customer.tax_id"] = (
            resolved["customer.tax_id"].confidence
        )
        if not is_valid_tax_id(cust_tax_id):
            warnings.append(
                f"CIF/NIF del cliente potencialmente inválido: {cust_tax_id}"
            )
            field_confidence["customer.tax_id"] *= 0.5
    else:
        warnings.append("CIF/NIF del cliente no encontrado.")
        field_confidence["customer.tax_id"] = 0.0

    # --- Customer legal_name ---
    cust_name = ""
    if "customer.legal_name" in resolved:
        cust_name = resolved["customer.legal_name"].value.strip()
        field_confidence["customer.legal_name"] = (
            resolved["customer.legal_name"].confidence
        )
    else:
        warnings.append("Razón social del cliente no encontrada.")
        field_confidence["customer.legal_name"] = 0.0

    # --- Tax lines ---
    tax_line_candidates: dict[str, dict[str, Candidate]] = {}
    for c in candidates.candidates:
        if c.field_name.startswith("tax_lines["):
            import re

            m = re.match(r"tax_lines\[([\d.]+)\]\.(\w+)", c.field_name)
            if m:
                rate_key = m.group(1)
                subfield = m.group(2)
                tax_line_candidates.setdefault(rate_key, {})[subfield] = c

    tax_lines: list[TaxLine] = []
    for rate_key, fields in sorted(tax_line_candidates.items()):
        base_c = fields.get("tax_base")
        amount_c = fields.get("tax_amount")
        if base_c and amount_c:
            try:
                base = normalize_money(base_c.value)
                amount = normalize_money(amount_c.value)
                rate_norm = str(Decimal(rate_key).normalize())
                tax_lines.append(_build_tax_line(rate_norm, base, amount))
                field_confidence[f"tax_lines[{rate_norm}]"] = (
                    base_c.confidence + amount_c.confidence
                ) / 2
            except Exception:
                pass

    if not tax_lines:
        warnings.append("No se detectaron líneas de IVA.")
        field_confidence["tax_lines"] = 0.0
    else:
        field_confidence["tax_lines"] = 0.65  # OCR es menos fiable que digital

    # --- Totals ---
    net_amount = Decimal("0.00")
    if "totals.net_amount" in resolved:
        try:
            net_amount = normalize_money(resolved["totals.net_amount"].value)
            field_confidence["totals.net_amount"] = (
                resolved["totals.net_amount"].confidence
            )
        except Exception:
            pass

    tax_amount = Decimal("0.00")
    if "totals.tax_amount" in resolved:
        try:
            tax_amount = normalize_money(resolved["totals.tax_amount"].value)
            field_confidence["totals.tax_amount"] = (
                resolved["totals.tax_amount"].confidence
            )
        except Exception:
            pass

    gross_amount = Decimal("0.00")
    if "totals.gross_amount" in resolved:
        try:
            gross_amount = normalize_money(resolved["totals.gross_amount"].value)
            field_confidence["totals.gross_amount"] = (
                resolved["totals.gross_amount"].confidence
            )
        except Exception:
            pass

    totals = Totals(
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
    )
    field_confidence["totals"] = (
        field_confidence.get("totals.net_amount", 0)
        + field_confidence.get("totals.tax_amount", 0)
        + field_confidence.get("totals.gross_amount", 0)
    ) / 3

    # 7. Validar totales con B2
    with stage_timer(timing, "validate_totals"):
        domain_tax_lines = [
            DomainTaxLineAmounts(
                tax_rate=Decimal(tl.tax_rate),
                tax_base=tl.tax_base,
                tax_amount=tl.tax_amount,
            )
            for tl in tax_lines
        ]
        domain_totals = DomainInvoiceTotals(
            net_amount=totals.net_amount,
            tax_amount=totals.tax_amount,
            gross_amount=totals.gross_amount,
        )
        domain_warnings = validate_totals(domain_tax_lines, domain_totals)
        warnings.extend(w.message for w in domain_warnings)

    # 8. Construir Invoice
    if inv_num and inv_date and sup_tax_id and cust_tax_id:
        invoice = Invoice(
            supplier=Party(legal_name=sup_name or "Desconocido", tax_id=sup_tax_id),
            customer=Party(legal_name=cust_name or "Desconocido", tax_id=cust_tax_id),
            invoice_data=InvoiceData(number=inv_num, issue_date=inv_date),
            tax_lines=tax_lines,
            totals=totals,
        )
    else:
        invoice = None
        warnings.append("Faltan campos obligatorios; respuesta marcada como error.")

    # 9. Confianza global (OCR típicamente menor)
    valid_confidences = [v for v in field_confidence.values() if v > 0]
    global_score = (
        sum(valid_confidences) / len(valid_confidences)
        if valid_confidences
        else 0.0
    )

    needs_review = [f for f, c in field_confidence.items() if c < 0.7]

    # 10. Evidencias
    evidence: dict[str, Evidence] = {}
    if include_evidence:
        for f, c in resolved.items():
            evidence[f] = _build_evidence(c)
        for rate_key, fields in tax_line_candidates.items():
            for subfield, c in fields.items():
                fkey = f"tax_lines[{rate_key}].{subfield}"
                evidence[fkey] = _build_evidence(c)

    debug: dict | None = None
    if include_debug:
        debug = {
            "stage": "ocr_pipeline",
            "kind": kind.value,
            "engine": ocr_engine.name(),
            "page_count": pdf_reader.page_count(pdf_source),
            "candidate_count": len(candidates.candidates),
            "resolved_fields": list(resolved.keys()),
            "timings": timing.to_dict(),
        }

    log_debug(
        "ocr_pipeline_completed",
        status="ok" if invoice else "error",
        kind=kind.value,
        candidate_count=len(candidates.candidates),
        resolved_count=len(resolved),
        global_score=global_score,
    )

    return InvoiceResponse(
        status="ok" if invoice else "error",
        invoice=invoice,
        confidence=ConfidenceReport(
            global_score=global_score,
            fields=field_confidence,
            needs_review=needs_review,
        ),
        warnings=warnings,
        errors=errors if invoice else errors,
        evidence=evidence,
        debug=debug,
    )