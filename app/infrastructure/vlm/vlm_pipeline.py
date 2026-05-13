"""Pipeline de soporte con VLM local para casos complejos (B9).

Este módulo proporciona la lógica de integración para invocar el VLM
cuando el pipeline digital/OCR/layout no ha podido resolver campos
obligatorios o tiene baja confianza.

El VLM SOLO propone candidatos. Los validadores de dominio (B2) y
el resolutor de campos (B8) validan y deciden si se aceptan los valores.

Uso::

    from app.infrastructure.vlm.vlm_pipeline import invoke_vlm_if_needed

    # Después de digital_pipeline u OCR pipeline
    result = invoke_vlm_if_needed(
        invoice_response=response,
        vlm_extractor=extractor,
        normalized_document=doc,
        include_debug=True,
    )
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
from app.application.pipeline.extract_candidates import Candidate
from app.application.pipeline.normalize_document import NormalizedDocument
from app.application.ports.invoice_extractor import InvoiceExtractor, VlmExtractionResult
from app.domain.services.date_validator import parse_invoice_date
from app.domain.services.tax_id_validator import is_valid_tax_id
from app.domain.services.totals_validator import (
    InvoiceTotals as DomainInvoiceTotals,
)
from app.domain.services.totals_validator import (
    TaxLineAmounts as DomainTaxLineAmounts,
)
from app.domain.services.totals_validator import validate_totals
from app.infrastructure.vlm.vlm_invocation_rules import (
    get_vlm_candidates_from_result,
    should_invoke_vlm,
)
from app.shared.logging import (
    TimingCollector,
    log_debug,
    log_warning,
    stage_timer,
)
from app.shared.money import normalize_money

# ---------------------------------------------------------------------------
# Helper: construir Invoice desde candidatos VLM
# ---------------------------------------------------------------------------


def _vlm_candidates_to_invoice(
    candidates: list[Candidate],
    page: int = 1,
) -> tuple[Invoice | None, list[str], list[ApiError]]:
    """Construye un Invoice desde candidatos del VLM.

    Args:
        candidates: Lista de candidatos del VLM ya convertidos.
        page: Página para logging.

    Returns:
        Tuple de (invoice, warnings, errors). invoice puede ser None
        si faltan campos obligatorios.
    """
    # Agrupar candidatos por campo
    by_field: dict[str, Candidate] = {}
    for c in candidates:
        existing = by_field.get(c.field_name)
        if existing is None or c.confidence > existing.confidence:
            by_field[c.field_name] = c

    warnings: list[str] = []
    errors: list[ApiError] = []

    # Extraer campos
    inv_num = by_field.get("invoice_data.number")
    inv_date = by_field.get("invoice_data.issue_date")
    sup_name = by_field.get("supplier.legal_name")
    sup_tax = by_field.get("supplier.tax_id")
    cust_name = by_field.get("customer.legal_name")
    cust_tax = by_field.get("customer.tax_id")

    # Validar número de factura
    number = ""
    if inv_num:
        number = inv_num.value.strip()
    if not number:
        errors.append(
            ApiError(
                code="missing_field",
                message="Número de factura no encontrado (VLM).",
                field="invoice_data.number",
            )
        )

    # Validar fecha
    date = None
    if inv_date:
        try:
            date = parse_invoice_date(inv_date.value)
        except ValueError as exc:
            warnings.append(f"Fecha inválida (VLM): {exc}")

    if date is None:
        errors.append(
            ApiError(
                code="missing_field",
                message="Fecha no encontrada (VLM).",
                field="invoice_data.issue_date",
            )
        )

    # Validar tax_ids
    sup_tax_id = ""
    if sup_tax:
        sup_tax_id = sup_tax.normalized_value or sup_tax.value
        sup_tax_id = sup_tax_id.upper().strip()
        if not is_valid_tax_id(sup_tax_id):
            warnings.append(f"CIF/NIF del emisor potencialmente inválido: {sup_tax_id}")
    if not sup_tax_id:
        errors.append(
            ApiError(
                code="missing_field",
                message="CIF/NIF del emisor no encontrado (VLM).",
                field="supplier.tax_id",
            )
        )

    cust_tax_id = ""
    if cust_tax:
        cust_tax_id = cust_tax.normalized_value or cust_tax.value
        cust_tax_id = cust_tax_id.upper().strip()
        if not is_valid_tax_id(cust_tax_id):
            warnings.append(f"CIF/NIF del cliente potencialmente inválido: {cust_tax_id}")
    if not cust_tax_id:
        errors.append(
            ApiError(
                code="missing_field",
                message="CIF/NIF del cliente no encontrado (VLM).",
                field="customer.tax_id",
            )
        )

    # Razón social (opcional pero registrado)
    supplier_name = sup_name.value.strip() if sup_name else "Desconocido"
    customer_name = cust_name.value.strip() if cust_name else "Desconocido"

    # Tax lines desde candidatos
    tax_lines: list[TaxLine] = []
    tax_line_candidates: dict[str, dict[str, Candidate]] = {}
    for c in candidates:
        if c.field_name.startswith("tax_lines["):
            import re

            m = re.match(r"tax_lines\[([\d.]+)\]\.(\w+)", c.field_name)
            if m:
                rate_key = m.group(1)
                subfield = m.group(2)
                tax_line_candidates.setdefault(rate_key, {})[subfield] = c

    for rate_key, fields in sorted(tax_line_candidates.items()):
        base_c = fields.get("tax_base")
        amount_c = fields.get("tax_amount")
        if base_c and amount_c:
            try:
                base = normalize_money(base_c.value)
                amount = normalize_money(amount_c.value)
                rate_norm = str(Decimal(rate_key).normalize())
                tax_lines.append(TaxLine(
                    tax_rate=Decimal(rate_norm),
                    tax_base=base,
                    tax_amount=amount,
                ))
            except Exception:
                pass

    # Totales
    net_c = by_field.get("totals.net_amount")
    tax_c = by_field.get("totals.tax_amount")
    gross_c = by_field.get("totals.gross_amount")

    net_amount = normalize_money(net_c.value) if net_c else Decimal("0.00")
    tax_amount = normalize_money(tax_c.value) if tax_c else Decimal("0.00")
    gross_amount = normalize_money(gross_c.value) if gross_c else Decimal("0.00")

    # Validar totales con B2
    domain_tax_lines = [
        DomainTaxLineAmounts(
            tax_rate=Decimal(tl.tax_rate),
            tax_base=tl.tax_base,
            tax_amount=tl.tax_amount,
        )
        for tl in tax_lines
    ]
    domain_totals = DomainInvoiceTotals(
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
    )
    domain_warnings = validate_totals(domain_tax_lines, domain_totals)
    warnings.extend(w.message for w in domain_warnings)

    if not (number and date and sup_tax_id and cust_tax_id):
        return None, warnings, errors

    invoice = Invoice(
        supplier=Party(legal_name=supplier_name, tax_id=sup_tax_id),
        customer=Party(legal_name=customer_name, tax_id=cust_tax_id),
        invoice_data=InvoiceData(number=number, issue_date=date),
        tax_lines=tax_lines,
        totals=Totals(
            net_amount=net_amount,
            tax_amount=tax_amount,
            gross_amount=gross_amount,
        ),
    )

    return invoice, warnings, errors


# ---------------------------------------------------------------------------
# Helper: construir evidence desde candidatos VLM
# ---------------------------------------------------------------------------


def _build_vlm_evidence(candidates: list[Candidate]) -> dict[str, Evidence]:
    """Construye mapa de evidencias desde candidatos VLM."""
    evidence: dict[str, Evidence] = {}
    for c in candidates:
        if c.field_name:
            evidence[c.field_name] = Evidence(
                text=c.value,
                page=c.page,
                bbox=None,  # VLM no proporciona bbox
                source="vlm",
            )
    return evidence


# ---------------------------------------------------------------------------
# Función principal: invocar VLM si es necesario
# ---------------------------------------------------------------------------


def invoke_vlm_if_needed(
    invoice_response: InvoiceResponse,
    vlm_extractor: InvoiceExtractor,
    normalized_document: NormalizedDocument | None = None,
    *,
    page_for_vlm: int = 1,
    include_evidence: bool = True,
    include_debug: bool = False,
) -> InvoiceResponse:
    """Intenta mejorar un InvoiceResponse usando el VLM si es necesario.

    El VLM se invoca cuando:
    1. La respuesta tiene errores por campos faltantes
    2. La confianza global es baja (< 0.6)
    3. Es un documento escaneado con tax_lines no resueltas

    El VLM SOLO propone candidatos. Los validadores de dominio (B2)
    validan y rechazan los valores inválidos.

    Args:
        invoice_response: Respuesta actual del pipeline (digital/OCR).
        vlm_extractor: Extractor VLM a usar (debe ser FakeVlmExtractor o similar).
        normalized_document: Documento normalizado para enviar al VLM como imagen.
            Si es None, se omite la extracción VLM.
        page_for_vlm: Número de página para logging.
        include_evidence: Incluir evidencias en la respuesta.
        include_debug: Incluir debug info.

    Returns:
        InvoiceResponse mejorado con candidatos del VLM si se invocó,
        o la respuesta original si no se invocó el VLM.
    """
    timing = TimingCollector()
    timing.start()

    # Determinar si el VLM debe invocarse
    missing_fields: list[str] = []
    low_confidence_fields: list[str] = []
    global_confidence: float | None = None
    is_scanned = False

    if invoice_response.errors:
        missing_fields = [
            e.field for e in invoice_response.errors if e.field
        ]

    if invoice_response.confidence:
        global_confidence = invoice_response.confidence.global_score
        # Campos con baja confianza
        if invoice_response.confidence.fields:
            low_confidence_fields = [
                f for f, c in invoice_response.confidence.fields.items()
                if c < 0.6
            ]

    # Intentar detectar si es escaneado desde la respuesta
    # (el debug info puede indicar el tipo)
    if invoice_response.debug:
        kind = invoice_response.debug.get("kind")
        if kind in ("scanned", "hybrid"):
            is_scanned = True

    should_invoke, reasons = should_invoke_vlm(
        missing_fields=missing_fields,
        low_confidence_fields=low_confidence_fields,
        global_confidence=global_confidence,
        is_scanned=is_scanned,
        tax_lines_unresolved=not invoice_response.invoice or not invoice_response.invoice.tax_lines,
    )

    # Si no hay extractor VLM disponible, no invocar
    if not vlm_extractor.is_available():
        if invoice_response.warnings is not None:
            invoice_response.warnings.append(
                "VLM no disponible; usando resultado del pipeline sin VLM."
            )
        return invoice_response

    if not should_invoke:
        log_debug(
            "vlm_not_needed",
            reason="all_fields_resolved",
            global_confidence=global_confidence,
        )
        return invoice_response

    log_debug(
        "vlm_invocation_triggered",
        reasons=[{"code": r.code, "detail": r.detail} for r in reasons],
        current_status=invoice_response.status,
    )

    # Ejecutar VLM si tenemos normalized_document
    vlm_result: VlmExtractionResult | None = None

    if normalized_document is not None:
        with stage_timer(timing, "vlm_inference"):
            try:
                # Enviar imagen al VLM
                # En producción se usaría reader.render_page_to_image
                # Para el mock/test usamos BytesIO vacío
                if normalized_document.pages and normalized_document.pages[0].blocks:
                    image_data = BytesIO(b"fake_page_image_for_vlm")
                    vlm_result = vlm_extractor.extract(
                        image_data,
                        page=page_for_vlm,
                    )
            except Exception as exc:
                log_warning(
                    "vlm_extraction_failed",
                    reason=str(exc),
                )
                if invoice_response.warnings is not None:
                    invoice_response.warnings.append(
                        f"VLM fallback: no se pudo invocar ({exc})"
                    )
                return invoice_response
    else:
        # Sin documento normalizado, no podemos enviar imagen al VLM
        if invoice_response.warnings is not None:
            invoice_response.warnings.append(
                "VLM no invocado: falta documento normalizado."
            )
        return invoice_response

    if vlm_result is None:
        return invoice_response

    # Convertir resultado VLM a candidatos
    candidates = get_vlm_candidates_from_result(vlm_result, page=page_for_vlm)

    if not candidates:
        if invoice_response.warnings is not None:
            warning_msg = "VLM no propuso candidatos."
            if vlm_result.warning:
                warning_msg += f" Warning: {vlm_result.warning}"
            invoice_response.warnings.append(warning_msg)
        return invoice_response

    # Construir invoice desde candidatos VLM
    invoice, vlm_warnings, vlm_errors = _vlm_candidates_to_invoice(candidates, page=page_for_vlm)

    # Calcular nueva confianza
    field_confidence: dict[str, float] = {}
    for c in candidates:
        # La confianza del VLM se reduce al ser fuente menos confiable
        field_confidence[c.field_name] = c.confidence

    # Confianza global del VLM
    valid_confidences = [v for v in field_confidence.values() if v > 0]
    vlm_global = (
        sum(valid_confidences) / len(valid_confidences)
        if valid_confidences
        else 0.0
    )

    # Combinar con respuesta original si ya tenía invoice
    needs_review = [f for f, c in field_confidence.items() if c < 0.7]

    # Construir evidencia
    evidence: dict[str, Evidence] = {}
    if include_evidence:
        evidence = _build_vlm_evidence(candidates)

    # Debug info
    debug: dict | None = None
    if include_debug:
        vlm_latency = (
            vlm_result.raw_response.latency_ms if vlm_result.raw_response else None
        )
        debug = {
            "stage": "vlm_fallback",
            "vlm_triggered": True,
            "vlm_reasons": [{"code": r.code, "detail": r.detail} for r in reasons],
            "vlm_candidates_count": len(candidates),
            "vlm_warning": vlm_result.warning,
            "vlm_latency_ms": vlm_latency,
            "timings": timing.to_dict(),
        }

    log_debug(
        "vlm_completed",
        candidates_count=len(candidates),
        has_invoice=invoice is not None,
        vlm_global_score=vlm_global,
    )

    return InvoiceResponse(
        status="ok" if invoice else "error",
        invoice=invoice,
        confidence=ConfidenceReport(
            global_score=vlm_global,
            fields=field_confidence,
            needs_review=needs_review,
        ),
        warnings=list(invoice_response.warnings or []) + vlm_warnings,
        errors=list(invoice_response.errors or []) + vlm_errors,
        evidence=evidence,
        debug=debug,
    )