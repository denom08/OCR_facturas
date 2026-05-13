"""Pipeline de extracción para PDFs digitales.

Coordina:
  1. Lectura del PDF (PdfReader)
  2. Normalización a NormalizedDocument
  3. Extracción de candidatos por patrones
  4. Validación con validadores de dominio (B2)
  5. Resolución básica de campos
  6. Montaje de InvoiceResponse con evidencias y confianza

No incluye OCR, XML ni VLM.
"""

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

# ---------------------------------------------------------------------------
# Construcción del documento normalizado desde el PDF reader
# ---------------------------------------------------------------------------


def _build_normalized_document(
    pdf_reader: PdfReader, pdf_source: BytesIO | str
) -> NormalizedDocument:
    """Convierte la salida del PdfReader en un NormalizedDocument."""

    blocks = pdf_reader.extract_text_blocks(pdf_source)

    normalized_blocks: list[NormalizedBlock] = []
    for blk in blocks:
        normalized_blocks.append(
            NormalizedBlock(
                text=blk.text,
                bbox=blk.bbox,
                page=blk.page,
                source=ExtractionSource.DIGITAL_TEXT,
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
        pages=pages, source=ExtractionSource.DIGITAL_TEXT
    )


# ---------------------------------------------------------------------------
# Helper: map candidato -> valor normalizado
# ---------------------------------------------------------------------------


def _candidate_value(c: Candidate, normalize_fn) -> object:
    """Intenta normalizar el valor del candidato con la función dada."""
    try:
        return normalize_fn(c.value)
    except Exception:
        return c.value


# ---------------------------------------------------------------------------
# Construcción de la respuesta
# ---------------------------------------------------------------------------


def _build_evidence(c: Candidate) -> Evidence:
    return Evidence(
        text=c.value,
        page=c.page,
        bbox=c.block.bbox if c.block else None,
        source="digital_text",
    )


def _build_tax_line(rate: str, base: Decimal, amount: Decimal) -> TaxLine:
    return TaxLine(
        tax_rate=rate,
        tax_base=base,
        tax_amount=amount,
    )


# ---------------------------------------------------------------------------
# Use case: procesar PDF digital
# ---------------------------------------------------------------------------


def process_digital_invoice(
    pdf_reader: PdfReader,
    pdf_source: BytesIO | str,
    *,
    include_evidence: bool = True,
    include_debug: bool = False,
) -> InvoiceResponse:
    """Procesa un PDF digital y devuelve un InvoiceResponse validado."""

    # Timing collector — para incluir en debug si include_debug=True
    timing = TimingCollector()
    timing.start()

    # 1. Clasificar — rechazamos si no es digital
    with stage_timer(timing, "pdf_classify"):
        kind = pdf_reader.classify(pdf_source)

    if kind not in (PdfKind.DIGITAL, PdfKind.HYBRID):
        log_warning(
            "digital_pipeline_rejected",
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
                        "se esperaba digital o híbrido."
                    ),
                    field="file",
                )
            ],
            evidence={},
            debug={"stage": "digital_pipeline", "kind": kind.value}
            if include_debug
            else None,
        )

    # 2. Normalizar documento
    with stage_timer(timing, "normalize_document"):
        doc = _build_normalized_document(pdf_reader, pdf_source)

    # 3. Extraer candidatos
    with stage_timer(timing, "extract_candidates"):
        candidates = extract_candidates(doc)

    # 4. Recoger mejores candidatos por campo
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

    # 5. Validar y resolver cada campo
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
        errors.append(
            ApiError(
                code="missing_field",
                message="Número de factura no encontrado.",
                field="invoice_data.number",
            )
        )

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
        errors.append(
            ApiError(
                code="missing_field",
                message="CIF/NIF del emisor no encontrado.",
                field="supplier.tax_id",
            )
        )

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
        errors.append(
            ApiError(
                code="missing_field",
                message="CIF/NIF del cliente no encontrado.",
                field="customer.tax_id",
            )
        )

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

    # --- Tax lines: reconstruir desde candidatos ---
    tax_line_candidates: dict[str, dict[str, Candidate]] = {}
    for c in candidates.candidates:
        if c.field_name.startswith("tax_lines["):
            import re

            # Captura tanto entero como decimal: tax_lines[21].x o tax_lines[21.0].x
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
                # Normalize rate: remove trailing .0 for clean output (21.0 -> "21")
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
        field_confidence["tax_lines"] = 0.75

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

    # 6. Validar totales con validador B2
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

    # 7. Construir Invoice si hay datos mínimos
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

    # 8. Confidence global
    valid_confidences = [v for v in field_confidence.values() if v > 0]
    global_score = (
        sum(valid_confidences) / len(valid_confidences)
        if valid_confidences
        else 0.0
    )

    needs_review = [f for f, c in field_confidence.items() if c < 0.7]

    # 9. Evidencias
    evidence: dict[str, Evidence] = {}
    if include_evidence:
        for f, c in resolved.items():
            evidence[f] = _build_evidence(c)
        for rate_key, fields in tax_line_candidates.items():
            for subfield, c in fields.items():
                fkey = f"tax_lines[{rate_key}].{subfield}"
                evidence[fkey] = _build_evidence(c)

    # 10. Debug
    debug: dict | None = None
    if include_debug:
        debug = {
            "stage": "digital_pipeline",
            "kind": kind.value,
            "candidate_count": len(candidates.candidates),
            "resolved_fields": list(resolved.keys()),
            "timings": timing.to_dict(),
        }

    log_debug(
        "digital_pipeline_completed",
        status="ok" if invoice else "error",
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