"""Parser mínimo para Facturae 3.2.

Facturae es el formato de factura electrónica español.
Este parser extrae los campos mínimos del schema:
- Datos de factura (número, fecha)
- Emisor (nombre, tax_id)
- Cliente (nombre, tax_id)
- Líneas de IVA (base, porcentaje, importe)
- Totales (base, IVA, total)

Extensible para versiones 3.1 y 4.x sin cambiar la arquitectura.
"""

import re
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET

from app.application.ports.xml_parser import ParsedInvoiceData, XmlFormat, XmlParser


def _local_tag(elem: ET.Element) -> str:
    """Extrae la parte local del tag, sin namespace."""
    return elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag


def _iter_children(element: ET.Element, tag: str) -> list[ET.Element]:
    """Busca hijos directos por tag local sin importar namespace."""
    return [child for child in element if _local_tag(child) == tag]


def _iter_all(element: ET.Element, tag: str) -> list[ET.Element]:
    """Busca todos los descendientes por tag local sin importar namespace."""
    return [child for child in element.iter() if _local_tag(child) == tag]


def _find_direct(element: ET.Element, tag: str) -> ET.Element | None:
    """Busca un hijo directo por tag local (sin namespace)."""
    return next((c for c in element if _local_tag(c) == tag), None)


def _text(element: ET.Element | None) -> str | None:
    """Extrae texto de un elemento, limpándolo."""
    if element is None:
        return None
    text = element.text
    if text is None:
        return None
    result = text.strip()
    return result if result else None


def _normalize_str(value: str | None) -> str | None:
    """Normaliza string de XML: limpia espacios y caracteres extraños."""
    if value is None:
        return None
    result = value.strip()
    result = re.sub(r"\s+", " ", result)
    return result if result else None


def _parse_invoice_number(root: ET.Element) -> str | None:
    """Extrae el número de factura."""
    # FacturaeHeader es hijo directo de root
    fh = _find_direct(root, "FacturaeHeader")
    if fh is not None:
        inv_num = _find_direct(fh, "InvoiceNumber")
        if inv_num is not None:
            return _text(inv_num)
    # Fallback: buscar en cualquier lugar
    for elem in _iter_all(root, "InvoiceNumber"):
        return _text(elem)
    return None


def _parse_invoice_date(root: ET.Element) -> str | None:
    """Extrae la fecha de factura."""
    fh = _find_direct(root, "FacturaeHeader")
    if fh is not None:
        inv_date = _find_direct(fh, "InvoiceDate")
        if inv_date is not None:
            return _text(inv_date)
    for elem in _iter_all(root, "InvoiceDate"):
        return _text(elem)
    return None


def _parse_party_name_and_tax_id(party_elem: ET.Element | None) -> tuple[str | None, str | None]:
    """Extrae nombre legal y tax_id de un Party (Seller o Buyer)."""
    if party_elem is None:
        return None, None

    name = None
    tax_id = None

    # LegalEntity puede estar anidado dentro del party
    le = _find_direct(party_elem, "LegalEntity")
    if le is None:
        le = party_elem  # fallback: el party mismo puede ser el legal entity

    if le is not None:
        name_elem = _find_direct(le, "CorporateName")
        if name_elem is None:
            name_elem = _find_direct(le, "Name")
        if name_elem is not None:
            name = _text(name_elem)

        # TaxIdentificationNumber puede estar en LegalEntity o directamente en Party
        tax_elem = _find_direct(le, "TaxIdentificationNumber")
        if tax_elem is None:
            tax_elem = _find_direct(party_elem, "TaxIdentificationNumber")
        if tax_elem is not None:
            # TaxIdentificationNumber tiene texto con el número
            tax_id = _text(tax_elem)
            if not tax_id:
                # Puede tener NumberStartDateOfValidTaxIdentification
                for child in tax_elem:
                    if _local_tag(child) == "NumberStartDateOfValidTaxIdentification":
                        tax_id = _text(child)
                        break

    # Fallback: buscar cualquier texto que parezca un CIF/NIF
    if not tax_id:
        for elem in party_elem.iter():
            text = _text(elem)
            if text and re.match(r"^[ABCDEFGHJKLMNPQRSUVW]\d{7}[\dA-J]$", text.strip()):
                tax_id = text.strip()
                break

    return name, tax_id


def _parse_taxes_outputs(root: ET.Element) -> list[dict[str, Any]]:
    """Extrae líneas de IVA de TaxesOutputs."""
    tax_lines: list[dict[str, Any]] = []

    # TaxesOutputs está dentro de FacturaeBody
    fb = _find_direct(root, "FacturaeBody")
    taxes_outputs = _find_direct(fb, "TaxesOutputs") if fb else None
    if taxes_outputs is None:
        taxes_outputs = _find_direct(root, "TaxesOutputs")
    if taxes_outputs is None:
        return tax_lines

    for tax_line in _iter_children(taxes_outputs, "TaxLine"):
        rate_val: Decimal | None = None
        base_val: Decimal | None = None
        amount_val: Decimal | None = None

        for child in tax_line:
            tag = _local_tag(child)
            text = _text(child)
            if text is None:
                continue
            if tag == "TaxRate":
                try:
                    rate_val = Decimal(text.replace(",", "."))
                except Exception:
                    pass
            elif tag == "TaxableBase":
                try:
                    base_val = Decimal(text.replace(",", "."))
                except Exception:
                    pass
            elif tag == "TaxAmount":
                try:
                    amount_val = Decimal(text.replace(",", "."))
                except Exception:
                    pass

        if rate_val is not None:
            tax_lines.append({
                "tax_rate": rate_val,
                "tax_base": base_val or Decimal("0"),
                "tax_amount": amount_val or Decimal("0"),
            })

    return tax_lines


def _parse_invoice_totals(
    root: ET.Element,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """Extrae totales de la factura."""
    # InvoiceTotals está dentro de FacturaeBody
    fb = _find_direct(root, "FacturaeBody")
    totals_elem = _find_direct(fb, "InvoiceTotals") if fb else None
    if totals_elem is None:
        totals_elem = _find_direct(root, "InvoiceTotals")

    def get_decimal(tag: str) -> Decimal | None:
        if totals_elem is None:
            return None
        child = _find_direct(totals_elem, tag)
        if child is None:
            return None
        text = _text(child)
        if text:
            try:
                return Decimal(text.replace(",", "."))
            except Exception:
                pass
        return None

    net = get_decimal("TotalGrossAmountBeforeTaxes")
    if net is None:
        net = get_decimal("TotalSums")
    tax = get_decimal("TotalTaxes")
    gross = get_decimal("InvoiceTotal")
    advance = get_decimal("TotalGeneralSurcharges")
    withholding = get_decimal("TotalPaymentsOnAccount")

    return net, tax, gross, advance, withholding


class FacturaeParser(XmlParser):
    """Parser para formato Facturae español."""

    def can_parse(self, format: XmlFormat) -> bool:
        return format == XmlFormat.FACTURAE

    def parse(self, xml_content: bytes) -> ParsedInvoiceData | None:
        """Parsea un XML Facturae y devuelve los datos extraídos."""
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return None

        # Verificar que es Facturae
        root_tag = _local_tag(root)
        if root_tag != "Facturae":
            return None

        # Extraer datos de factura
        invoice_number = _parse_invoice_number(root)
        issue_date = _parse_invoice_date(root)

        # Partes: emisor y cliente
        # FacturaeBody es hijo directo de root, Parties está dentro de FacturaeBody
        fb = _find_direct(root, "FacturaeBody")
        parties_elem = _find_direct(fb, "Parties") if fb else None

        supplier_name = None
        supplier_tax_id = None
        customer_name = None
        customer_tax_id = None

        if parties_elem is not None:
            seller = _find_direct(parties_elem, "SellerParty")
            if seller is not None:
                supplier_name, supplier_tax_id = _parse_party_name_and_tax_id(seller)

            buyer = _find_direct(parties_elem, "BuyerParty")
            if buyer is not None:
                customer_name, customer_tax_id = _parse_party_name_and_tax_id(buyer)

        # Totales
        net, tax, gross, advance, withholding = _parse_invoice_totals(root)

        # Líneas de IVA
        tax_lines = _parse_taxes_outputs(root)

        if not any([invoice_number, issue_date, supplier_name, supplier_tax_id]):
            return None

        return ParsedInvoiceData(
            invoice_number=_normalize_str(invoice_number),
            issue_date=_normalize_str(issue_date),
            supplier_name=_normalize_str(supplier_name),
            supplier_tax_id=_normalize_str(supplier_tax_id),
            customer_name=_normalize_str(customer_name),
            customer_tax_id=_normalize_str(customer_tax_id),
            tax_lines=tax_lines if tax_lines else None,
            net_amount=net,
            tax_amount=tax,
            gross_amount=gross,
            advance_amount=advance,
            withholding_amount=withholding,
            raw_xml=xml_content,
        )