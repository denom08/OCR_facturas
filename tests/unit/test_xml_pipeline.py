"""Tests para el pipeline de XML embebido."""

from decimal import Decimal
from io import BytesIO

import fitz
import pytest

from app.application.pipeline.xml_pipeline import process_xml_invoice
from app.infrastructure.xml import FacturaeParser, PyMuPdfEmbeddedXmlExtractor


def _make_pdf_with_xml(xml_content: bytes, filename: str = "facturae.xml") -> BytesIO:
    """Helper: crea un PDF con un XML embebido."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Factura electrónica", fontname="helv")
    doc.embfile_add(filename, xml_content)
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


@pytest.fixture
def facturae_32_pdf() -> BytesIO:
    """PDF con XML Facturae 3.2 completo."""
    # B64188642 → CIF válido, 00000000T → NIF válido
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Facturae xmlns="http://www.facturae.es/Facturae/32">\n'
        b'  <FacturaeHeader>\n'
        b'    <InvoiceNumber>2024/001</InvoiceNumber>\n'
        b'    <InvoiceDate>2024-01-15</InvoiceDate>\n'
        b'  </FacturaeHeader>\n'
        b'  <FacturaeBody>\n'
        b'    <Parties>\n'
        b'      <SellerParty>\n'
        b'        <LegalEntity>\n'
        b'          <CorporateName>Acme Corporation S.L.</CorporateName>\n'
        b'          <TaxIdentificationNumber>B64188642</TaxIdentificationNumber>\n'
        b'        </LegalEntity>\n'
        b'      </SellerParty>\n'
        b'      <BuyerParty>\n'
        b'        <LegalEntity>\n'
        b'          <CorporateName>Cliente Test S.A.</CorporateName>\n'
        b'          <TaxIdentificationNumber>00000000T</TaxIdentificationNumber>\n'
        b'        </LegalEntity>\n'
        b'      </BuyerParty>\n'
        b'    </Parties>\n'
        b'    <InvoiceTotals>\n'
        b'      <TotalGrossAmountBeforeTaxes>1000.00</TotalGrossAmountBeforeTaxes>\n'
        b'      <TotalTaxes>210.00</TotalTaxes>\n'
        b'      <InvoiceTotal>1210.00</InvoiceTotal>\n'
        b'    </InvoiceTotals>\n'
        b'    <TaxesOutputs>\n'
        b'      <TaxLine>\n'
        b'        <TaxTypeCode>IVA</TaxTypeCode>\n'
        b'        <TaxRate>21.00</TaxRate>\n'
        b'        <TaxableBase>1000.00</TaxableBase>\n'
        b'        <TaxAmount>210.00</TaxAmount>\n'
        b'      </TaxLine>\n'
        b'    </TaxesOutputs>\n'
        b'  </FacturaeBody>\n'
        b'</Facturae>'
    )
    return _make_pdf_with_xml(xml, "facturae.xml")


@pytest.fixture
def facturae_multitax_pdf() -> BytesIO:
    """PDF con Facturae y múltiples tipos de IVA."""
    # B64188642 → CIF válido, 00000000T → NIF válido
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Facturae xmlns="http://www.facturae.es/Facturae/32">\n'
        b'  <FacturaeHeader>\n'
        b'    <InvoiceNumber>2024/050</InvoiceNumber>\n'
        b'    <InvoiceDate>2024-03-20</InvoiceDate>\n'
        b'  </FacturaeHeader>\n'
        b'  <FacturaeBody>\n'
        b'    <Parties>\n'
        b'      <SellerParty>\n'
        b'        <LegalEntity>\n'
        b'          <CorporateName>Proveedor Multitasa S.L.</CorporateName>\n'
        b'          <TaxIdentificationNumber>B64188642</TaxIdentificationNumber>\n'
        b'        </LegalEntity>\n'
        b'      </SellerParty>\n'
        b'      <BuyerParty>\n'
        b'        <LegalEntity>\n'
        b'          <CorporateName>Empresa Test S.A.</CorporateName>\n'
        b'          <TaxIdentificationNumber>00000000T</TaxIdentificationNumber>\n'
        b'        </LegalEntity>\n'
        b'      </BuyerParty>\n'
        b'    </Parties>\n'
        b'    <InvoiceTotals>\n'
        b'      <TotalGrossAmountBeforeTaxes>1600.00</TotalGrossAmountBeforeTaxes>\n'
        b'      <TotalTaxes>282.00</TotalTaxes>\n'
        b'      <InvoiceTotal>1882.00</InvoiceTotal>\n'
        b'    </InvoiceTotals>\n'
        b'    <TaxesOutputs>\n'
        b'      <TaxLine>\n'
        b'        <TaxTypeCode>IVA</TaxTypeCode>\n'
        b'        <TaxRate>21.00</TaxRate>\n'
        b'        <TaxableBase>1000.00</TaxableBase>\n'
        b'        <TaxAmount>210.00</TaxAmount>\n'
        b'      </TaxLine>\n'
        b'      <TaxLine>\n'
        b'        <TaxTypeCode>IVA</TaxTypeCode>\n'
        b'        <TaxRate>10.00</TaxRate>\n'
        b'        <TaxableBase>600.00</TaxableBase>\n'
        b'        <TaxAmount>60.00</TaxAmount>\n'
        b'      </TaxLine>\n'
        b'      <TaxLine>\n'
        b'        <TaxTypeCode>IVA</TaxTypeCode>\n'
        b'        <TaxRate>4.00</TaxRate>\n'
        b'        <TaxableBase>300.00</TaxableBase>\n'
        b'        <TaxAmount>12.00</TaxAmount>\n'
        b'      </TaxLine>\n'
        b'    </TaxesOutputs>\n'
        b'  </FacturaeBody>\n'
        b'</Facturae>'
    )
    return _make_pdf_with_xml(xml, "facturae.xml")


@pytest.fixture
def pdf_without_xml() -> BytesIO:
    """PDF sin XML embebido."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Factura digital sin XML", fontname="helv")
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


@pytest.fixture
def pdf_with_unparseable_xml() -> BytesIO:
    """PDF con XML no reconocido por ningún parser."""
    xml = b'<?xml version="1.0"?><SomeUnknownFormat>test</SomeUnknownFormat>'
    return _make_pdf_with_xml(xml, "unknown.xml")


class TestProcessXmlInvoice:
    """Tests para process_xml_invoice."""

    def get_extractor(self) -> PyMuPdfEmbeddedXmlExtractor:
        return PyMuPdfEmbeddedXmlExtractor()

    def get_parser(self) -> FacturaeParser:
        return FacturaeParser()

    def test_process_facturae_pdf(self, facturae_32_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "ok"
        assert result.invoice is not None
        assert result.invoice.invoice_data.number == "2024/001"
        assert result.invoice.supplier.legal_name == "Acme Corporation S.L."
        assert result.invoice.supplier.tax_id == "B64188642"
        assert result.invoice.customer.legal_name == "Cliente Test S.A."
        assert result.invoice.customer.tax_id == "00000000T"
        assert len(result.invoice.tax_lines) == 1
        assert result.invoice.totals.gross_amount == Decimal("1210.00")

    def test_process_multitax_facturae(self, facturae_multitax_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_multitax_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "ok"
        assert result.invoice is not None
        assert result.invoice.invoice_data.number == "2024/050"
        assert len(result.invoice.tax_lines) == 3

    def test_process_no_xml(self, pdf_without_xml: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=pdf_without_xml,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "error"
        assert result.errors[0].code == "no_xml_found"

    def test_process_unparseable_xml(self, pdf_with_unparseable_xml: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=pdf_with_unparseable_xml,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "error"
        assert result.errors[0].code == "xml_parse_failed"

    def test_process_xml_evidence(self, facturae_32_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "ok"
        assert "invoice_data.number" in result.evidence
        assert result.evidence["invoice_data.number"].source == "xml"
        assert "supplier.tax_id" in result.evidence

    def test_process_xml_no_evidence(self, facturae_32_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=False,
            include_debug=False,
        )
        assert result.status == "ok"
        assert result.evidence == {}

    def test_process_xml_debug(self, facturae_32_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=False,
            include_debug=True,
        )
        assert result.status == "ok"
        assert result.debug is not None
        assert result.debug["stage"] == "xml_pipeline"
        assert result.debug["format"] == "facturae"

    def test_process_xml_high_confidence(self, facturae_32_pdf: BytesIO):
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        assert result.status == "ok"
        assert result.confidence.global_score > 0.9
        assert "invoice_data.number" not in result.confidence.needs_review

    def test_process_validates_totals(self, facturae_32_pdf: BytesIO):
        """El pipeline valida totales con B2 y genera warnings si no cuadran."""
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        # Totales correctos: no debe haber warnings de totales
        total_warnings = [
            w for w in result.warnings
            if "mismatch" in w or "cuadra" in w
        ]
        assert len(total_warnings) == 0

    def test_process_tax_id_validation(self, facturae_32_pdf: BytesIO):
        """Tax IDs válidos no generan warnings."""
        extractor = self.get_extractor()
        parser = self.get_parser()
        result = process_xml_invoice(
            xml_extractor=extractor,
            pdf_source=facturae_32_pdf,
            parsers=[parser],
            include_evidence=True,
            include_debug=False,
        )
        tax_id_warnings = [
            w for w in result.warnings
            if "inválido" in w.lower() or "potencialmente" in w.lower()
        ]
        assert len(tax_id_warnings) == 0