"""Pipeline para extracción desde XML embebido (Facturae / UBL / CII).

Prioriza datos estructurados XML sobre texto digital o OCR.
Aplica validadores B2 al resultado y genera InvoiceResponse.
"""

from datetime import date
from decimal import Decimal

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
from app.application.ports.xml_extractor import (
    EmbeddedXmlExtractor,
    XmlFormat,
)
from app.application.ports.xml_parser import ParsedInvoiceData, XmlParser
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


def _build_tax_line(rate: str, base: Decimal, amount: Decimal) -> TaxLine:
    return TaxLine(
        tax_rate=Decimal(rate),
        tax_base=base,
        tax_amount=amount,
    )


def _build_evidence_from_xml(parsed: ParsedInvoiceData) -> Evidence:
    return Evidence(
        text=parsed.invoice_number or "unknown",
        page=1,
        bbox=None,
        source="xml",
    )


def _map_parsed_to_invoice(
    parsed: ParsedInvoiceData,
) -> tuple[Invoice, list[str], dict[str, Evidence]]:
    """Mapea ParsedInvoiceData a modelo Invoice y devuelve invoice, warnings, evidence."""
    warnings: list[str] = []
    evidence: dict[str, Evidence] = {}

    # Número de factura
    inv_number = parsed.invoice_number or ""
    if not inv_number:
        warnings.append("Número de factura no encontrado en XML.")
    evidence["invoice_data.number"] = Evidence(
        text=inv_number, page=1, bbox=None, source="xml"
    )

    # Fecha
    inv_date: date | None = None
    if parsed.issue_date:
        try:
            inv_date = parse_invoice_date(parsed.issue_date)
        except ValueError as exc:
            warnings.append(f"Fecha inválida del XML: {exc}")
    else:
        warnings.append("Fecha de factura no encontrada en XML.")
    evidence["invoice_data.issue_date"] = Evidence(
        text=str(parsed.issue_date or ""), page=1, bbox=None, source="xml"
    )

    # Emisor
    sup_name = parsed.supplier_name or ""
    sup_tax_id = parsed.supplier_tax_id or ""
    if not sup_name:
        warnings.append("Razón social del emisor no encontrada en XML.")
    if not sup_tax_id:
        warnings.append("Tax ID del emisor no encontrado en XML.")
    elif not is_valid_tax_id(sup_tax_id):
        warnings.append(f"CIF/NIF del emisor potencialmente inválido: {sup_tax_id}")
    evidence["supplier.tax_id"] = Evidence(
        text=sup_tax_id, page=1, bbox=None, source="xml"
    )
    evidence["supplier.legal_name"] = Evidence(
        text=sup_name, page=1, bbox=None, source="xml"
    )

    # Cliente
    cust_name = parsed.customer_name or ""
    cust_tax_id = parsed.customer_tax_id or ""
    if not cust_name:
        warnings.append("Razón social del cliente no encontrada en XML.")
    if not cust_tax_id:
        warnings.append("Tax ID del cliente no encontrado en XML.")
    elif not is_valid_tax_id(cust_tax_id):
        warnings.append(f"CIF/NIF del cliente potencialmente inválido: {cust_tax_id}")
    evidence["customer.tax_id"] = Evidence(
        text=cust_tax_id, page=1, bbox=None, source="xml"
    )
    evidence["customer.legal_name"] = Evidence(
        text=cust_name, page=1, bbox=None, source="xml"
    )

    # Tax lines
    tax_lines: list[TaxLine] = []
    if parsed.tax_lines:
        for tl in parsed.tax_lines:
            rate = str(tl.get("tax_rate", "0"))
            base = tl.get("tax_base", Decimal("0"))
            amount = tl.get("tax_amount", Decimal("0"))
            if isinstance(base, Decimal) and isinstance(amount, Decimal):
                tax_lines.append(_build_tax_line(rate, base, amount))
                evidence[f"tax_lines[{rate}].tax_rate"] = Evidence(
                    text=rate, page=1, bbox=None, source="xml"
                )
                evidence[f"tax_lines[{rate}].tax_base"] = Evidence(
                    text=str(base), page=1, bbox=None, source="xml"
                )
                evidence[f"tax_lines[{rate}].tax_amount"] = Evidence(
                    text=str(amount), page=1, bbox=None, source="xml"
                )
    else:
        warnings.append("No se encontraron líneas de IVA en XML.")

    # Totales
    net_amount = parsed.net_amount or Decimal("0.00")
    tax_amount = parsed.tax_amount or Decimal("0.00")
    gross_amount = parsed.gross_amount or Decimal("0.00")
    advance_amount = parsed.advance_amount
    withholding_amount = parsed.withholding_amount

    evidence["totals.net_amount"] = Evidence(
        text=str(net_amount), page=1, bbox=None, source="xml"
    )
    evidence["totals.tax_amount"] = Evidence(
        text=str(tax_amount), page=1, bbox=None, source="xml"
    )
    evidence["totals.gross_amount"] = Evidence(
        text=str(gross_amount), page=1, bbox=None, source="xml"
    )

    # Construir Invoice si hay datos mínimos
    if not (inv_number and inv_date and sup_tax_id and cust_tax_id):
        raise ValueError("Faltan campos obligatorios en XML.")

    invoice = Invoice(
        supplier=Party(legal_name=sup_name or "Desconocido", tax_id=sup_tax_id),
        customer=Party(legal_name=cust_name or "Desconocido", tax_id=cust_tax_id),
        invoice_data=InvoiceData(number=inv_number, issue_date=inv_date),
        tax_lines=tax_lines,
        totals=Totals(
            net_amount=net_amount,
            tax_amount=tax_amount,
            gross_amount=gross_amount,
            advance_amount=advance_amount,
            withholding_amount=withholding_amount,
        ),
    )

    return invoice, warnings, evidence


def process_xml_invoice(
    xml_extractor: EmbeddedXmlExtractor,
    pdf_source,
    parsers: list[XmlParser],
    *,
    include_evidence: bool = True,
    include_debug: bool = False,
) -> InvoiceResponse:
    """Procesa un PDF con XML embebido y devuelve un InvoiceResponse.

    Params:
    - xml_extractor: extractor de XML embebido (PyMuPdfEmbeddedXmlExtractor)
    - pdf_source: BytesIO o str con el PDF
    - parsers: lista de XmlParser (Facturae, UBL, CII)
    - include_evidence: si True, incluye evidencias
    - include_debug: si True, incluye debug

    Estrategia:
    1. Extraer XMLs embebidos del PDF
    2. Para cada XML, detectar formato e intentar parsear con cada parser
    3. Si un parser logra extraer datos, usar ese resultado
    4. Validar totales con B2
    5. Devolver InvoiceResponse con evidencia y confianza alta
    """
    # Timing collector
    timing = TimingCollector()
    timing.start()

    # 1. Extraer XMLs embebidos
    with stage_timer(timing, "xml_extract"):
        xmls = xml_extractor.extract_embedded_xmls(pdf_source)

    if not xmls:
        log_warning("xml_pipeline_no_xml_found")
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=["No se encontraron XMLs embebidos en el PDF."],
            errors=[
                ApiError(
                    code="no_xml_found",
                    message="El PDF no contiene XML embebido.",
                    field="file",
                )
            ],
            evidence={},
            debug={"stage": "xml_pipeline", "xml_count": 0} if include_debug else None,
        )

    # 2. Intentar parsear con cada parser
    with stage_timer(timing, "xml_parse", xml_count=len(xmls)):
        parsed_data: ParsedInvoiceData | None = None
        used_format: XmlFormat = XmlFormat.UNKNOWN

        for xml_obj in xmls:
            for parser in parsers:
                if parser.can_parse(xml_obj.format):
                    result = parser.parse(xml_obj.raw_xml)
                    if result is not None:
                        parsed_data = result
                        used_format = xml_obj.format
                        break
            if parsed_data is not None:
                break

        # 3. Si nadie pudo, intentar con formato unknown
        if parsed_data is None:
            for xml_obj in xmls:
                for parser in parsers:
                    if parser.can_parse(XmlFormat.UNKNOWN):
                        result = parser.parse(xml_obj.raw_xml)
                        if result is not None:
                            parsed_data = result
                            used_format = xml_obj.format
                            break
                if parsed_data is not None:
                    break

    if parsed_data is None:
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[f"XML encontrado pero no pudo ser parseado: {xml_obj.format.value}"],
            errors=[
                ApiError(
                    code="xml_parse_failed",
                    message=f"No se reconoció el formato XML: {xml_obj.format.value}",
                    field="file",
                )
            ],
            evidence={},
            debug={
                "stage": "xml_pipeline",
                "xml_count": len(xmls),
                "formats": [x.format.value for x in xmls],
            } if include_debug else None,
        )

    # 4. Mapear a Invoice
    try:
        invoice, map_warnings, evidence = _map_parsed_to_invoice(parsed_data)
    except ValueError as exc:
        return InvoiceResponse(
            status="error",
            invoice=None,
            confidence=ConfidenceReport(global_score=0.0),
            warnings=[str(exc)],
            errors=[
                ApiError(
                    code="xml_invalid_data",
                    message=str(exc),
                    field="file",
                )
            ],
            evidence={},
            debug={"stage": "xml_pipeline", "format": used_format.value} if include_debug else None,
        )

    # 5. Validar totales con B2
    with stage_timer(timing, "validate_totals"):
        domain_tax_lines = [
            DomainTaxLineAmounts(
                tax_rate=tl.tax_rate,
                tax_base=tl.tax_base,
                tax_amount=tl.tax_amount,
            )
            for tl in invoice.tax_lines
        ]
        domain_totals = DomainInvoiceTotals(
            net_amount=invoice.totals.net_amount,
            tax_amount=invoice.totals.tax_amount,
            gross_amount=invoice.totals.gross_amount,
            advance_amount=invoice.totals.advance_amount,
            withholding_amount=invoice.totals.withholding_amount,
        )
        domain_warnings = validate_totals(domain_tax_lines, domain_totals)
        map_warnings.extend(w.message for w in domain_warnings)

    # 6. Calcular confianza (XML = alta)
    all_warnings = map_warnings
    field_confidence: dict[str, float] = {}

    # Alta confianza para campos presentes
    for field in (
        "invoice_data.number",
        "invoice_data.issue_date",
        "supplier.tax_id",
        "supplier.legal_name",
        "customer.tax_id",
        "customer.legal_name",
        "totals.net_amount",
        "totals.tax_amount",
        "totals.gross_amount",
    ):
        field_confidence[field] = 0.95

    for tl in invoice.tax_lines:
        rate_key = str(tl.tax_rate.normalize())
        field_confidence[f"tax_lines[{rate_key}]"] = 0.95

    if invoice.tax_lines:
        field_confidence["tax_lines"] = 0.95

    valid_confidences = [v for v in field_confidence.values() if v > 0]
    global_score = sum(valid_confidences) / len(valid_confidences) if valid_confidences else 0.0

    needs_review = [f for f, c in field_confidence.items() if c < 0.7]

    log_debug(
        "xml_pipeline_completed",
        status="ok",
        format=used_format.value,
        xml_count=len(xmls),
        global_score=global_score,
    )

    return InvoiceResponse(
        status="ok",
        invoice=invoice,
        confidence=ConfidenceReport(
            global_score=global_score,
            fields=field_confidence,
            needs_review=needs_review,
        ),
        warnings=all_warnings,
        errors=[],
        evidence=evidence if include_evidence else {},
        debug={
            "stage": "xml_pipeline",
            "format": used_format.value,
            "xml_count": len(xmls),
            "timings": timing.to_dict(),
        } if include_debug else None,
    )