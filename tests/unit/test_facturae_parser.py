"""Tests para el parser de Facturae."""

import pytest

from app.application.ports.xml_extractor import XmlFormat
from app.infrastructure.xml import FacturaeParser

# B64188642 → CIF válido para test (B + 7 dígitos + control dígito 2)
FACTURAE_TAX_ID_SUPPLIER = "B64188642"
# A00000000 → NIF válido (cálculo: 0 % 23 = 0 → T)
FACTURAE_TAX_ID_CUSTOMER = "00000000T"


@pytest.fixture
def facturae_32_xml() -> bytes:
    """XML Facturae 3.2 válido con datos completos."""
    return (
        b"""<?xml version="1.0" encoding="UTF-8"?>
<Facturae xmlns="http://www.facturae.es/Facturae/32">
  <FileHeader>
    <SchemaVersion>3.2</SchemaVersion>
  </FileHeader>
  <FacturaeHeader>
    <InvoiceNumber>2024/001</InvoiceNumber>
    <InvoiceDate>2024-01-15</InvoiceDate>
  </FacturaeHeader>
  <FacturaeBody>
    <Parties>
      <SellerParty>
        <LegalEntity>
          <CorporateName>Acme Corporation S.L.</CorporateName>
          <TaxIdentificationNumber>"""
        + FACTURAE_TAX_ID_SUPPLIER.encode()
        + b"""</TaxIdentificationNumber>
        </LegalEntity>
      </SellerParty>
      <BuyerParty>
        <LegalEntity>
          <CorporateName>Cliente Ejemplo S.A.</CorporateName>
          <TaxIdentificationNumber>"""
        + FACTURAE_TAX_ID_CUSTOMER.encode()
        + b"""</TaxIdentificationNumber>
        </LegalEntity>
      </BuyerParty>
    </Parties>
    <InvoiceTotals>
      <TotalGrossAmountBeforeTaxes>1000.00</TotalGrossAmountBeforeTaxes>
      <TotalTaxes>210.00</TotalTaxes>
      <InvoiceTotal>1210.00</InvoiceTotal>
    </InvoiceTotals>
    <TaxesOutputs>
      <TaxLine>
        <TaxTypeCode>IVA</TaxTypeCode>
        <TaxRate>21.00</TaxRate>
        <TaxableBase>1000.00</TaxableBase>
        <TaxAmount>210.00</TaxAmount>
      </TaxLine>
    </TaxesOutputs>
  </FacturaeBody>
</Facturae>"""
    )


@pytest.fixture
def facturae_32_multitax_xml() -> bytes:
    """XML Facturae 3.2 con múltiples tipos de IVA."""
    return (
        b"""<?xml version="1.0" encoding="UTF-8"?>
<Facturae xmlns="http://www.facturae.es/Facturae/32">
  <FileHeader>
    <SchemaVersion>3.2</SchemaVersion>
  </FileHeader>
  <FacturaeHeader>
    <InvoiceNumber>2024/050</InvoiceNumber>
    <InvoiceDate>2024-03-20</InvoiceDate>
  </FacturaeHeader>
  <FacturaeBody>
    <Parties>
      <SellerParty>
        <LegalEntity>
          <CorporateName>Proveedor Multitasa S.L.</CorporateName>
          <TaxIdentificationNumber>"""
        + FACTURAE_TAX_ID_SUPPLIER.encode()
        + b"""</TaxIdentificationNumber>
        </LegalEntity>
      </SellerParty>
      <BuyerParty>
        <LegalEntity>
          <CorporateName>Empresa Test S.A.</CorporateName>
          <TaxIdentificationNumber>"""
        + FACTURAE_TAX_ID_CUSTOMER.encode()
        + b"""</TaxIdentificationNumber>
        </LegalEntity>
      </BuyerParty>
    </Parties>
    <InvoiceTotals>
      <TotalGrossAmountBeforeTaxes>1500.00</TotalGrossAmountBeforeTaxes>
      <TotalTaxes>265.00</TotalTaxes>
      <InvoiceTotal>1765.00</InvoiceTotal>
    </InvoiceTotals>
    <TaxesOutputs>
      <TaxLine>
        <TaxTypeCode>IVA</TaxTypeCode>
        <TaxRate>21.00</TaxRate>
        <TaxableBase>1000.00</TaxableBase>
        <TaxAmount>210.00</TaxAmount>
      </TaxLine>
      <TaxLine>
        <TaxTypeCode>IVA</TaxTypeCode>
        <TaxRate>10.00</TaxRate>
        <TaxableBase>500.00</TaxableBase>
        <TaxAmount>50.00</TaxAmount>
      </TaxLine>
      <TaxLine>
        <TaxTypeCode>IVA</TaxTypeCode>
        <TaxRate>5.00</TaxRate>
        <TaxableBase>100.00</TaxableBase>
        <TaxAmount>5.00</TaxAmount>
      </TaxLine>
    </TaxesOutputs>
  </FacturaeBody>
</Facturae>"""
    )


@pytest.fixture
def facturae_minimal_xml() -> bytes:
    """XML Facturae con solo campos obligatorios."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<Facturae xmlns="http://www.facturae.es/Facturae/32">
  <FacturaeHeader>
    <InvoiceNumber>MIN/001</InvoiceNumber>
    <InvoiceDate>2024-01-01</InvoiceDate>
  </FacturaeHeader>
  <FacturaeBody>
    <Parties>
      <SellerParty>
        <LegalEntity>
          <CorporateName>Emisor Minimal S.L.</CorporateName>
          <TaxIdentificationNumber>B00000000</TaxIdentificationNumber>
        </LegalEntity>
      </SellerParty>
    </Parties>
  </FacturaeBody>
</Facturae>"""


@pytest.fixture
def invalid_xml() -> bytes:
    """XML que no es Facturae."""
    return b"""<?xml version="1.0"?><SomeOtherFormat>test</SomeOtherFormat>"""


@pytest.fixture
def malformed_xml() -> bytes:
    """XML malformado (no parseable)."""
    return b"""<?xml version="1.0"?><Facturae><unclosed>"""


class TestFacturaeParser:
    """Tests para FacturaeParser."""

    def get_parser(self) -> FacturaeParser:
        return FacturaeParser()

    def test_can_parse_facturae(self):
        parser = self.get_parser()
        assert parser.can_parse(XmlFormat.FACTURAE) is True
        assert parser.can_parse(XmlFormat.UBL) is False
        assert parser.can_parse(XmlFormat.CII) is False
        assert parser.can_parse(XmlFormat.UNKNOWN) is False

    def test_parse_valid_facturae(self, facturae_32_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(facturae_32_xml)
        assert result is not None
        assert result.invoice_number == "2024/001"
        assert result.issue_date == "2024-01-15"
        assert result.supplier_name == "Acme Corporation S.L."
        assert result.supplier_tax_id == "B64188642"
        assert result.customer_name == "Cliente Ejemplo S.A."
        assert result.customer_tax_id == "00000000T"
        assert result.net_amount is not None
        assert result.gross_amount is not None

    def test_parse_multitax_facturae(self, facturae_32_multitax_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(facturae_32_multitax_xml)
        assert result is not None
        assert result.invoice_number == "2024/050"
        assert result.tax_lines is not None
        assert len(result.tax_lines) == 3
        rates = [str(int(tl["tax_rate"])) for tl in result.tax_lines]
        assert "21" in rates
        assert "10" in rates
        assert "5" in rates

    def test_parse_minimal_facturae(self, facturae_minimal_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(facturae_minimal_xml)
        assert result is not None
        assert result.invoice_number == "MIN/001"
        assert result.supplier_name == "Emisor Minimal S.L."
        assert result.supplier_tax_id == "B00000000"

    def test_parse_invalid_format(self, invalid_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(invalid_xml)
        assert result is None

    def test_parse_malformed_xml(self, malformed_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(malformed_xml)
        assert result is None

    def test_parse_preserves_raw_xml(self, facturae_32_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(facturae_32_xml)
        assert result is not None
        assert result.raw_xml == facturae_32_xml

    def test_parse_with_whitespace_in_tax_id(self, facturae_32_xml: bytes):
        """Los espacios en blanco en TaxIdentificationNumber deben ser eliminados."""
        parser = self.get_parser()
        result = parser.parse(facturae_32_xml)
        assert result is not None
        assert " " not in result.supplier_tax_id

    def test_tax_lines_are_dicts(self, facturae_32_multitax_xml: bytes):
        parser = self.get_parser()
        result = parser.parse(facturae_32_multitax_xml)
        assert result is not None
        assert result.tax_lines is not None
        for tl in result.tax_lines:
            assert isinstance(tl, dict)
            assert "tax_rate" in tl
            assert "tax_base" in tl
            assert "tax_amount" in tl