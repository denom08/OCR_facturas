"""Tests para el extractor de XML embebido."""

from io import BytesIO

import fitz
import pytest

from app.application.ports.xml_extractor import (
    EmbeddedXml,
    XmlFormat,
)
from app.infrastructure.xml import PyMuPdfEmbeddedXmlExtractor


@pytest.fixture
def pdf_with_facturae_xml() -> BytesIO:
    """PDF con XML Facturae embebido como archivo."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Factura con XML embebido", fontname="helv")

    xml_content = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Facturae xmlns="http://www.facturae.es/Facturae/32">\n'
        b'  <FileHeader>\n'
        b'    <SchemaVersion>3.2</SchemaVersion>\n'
        b'  </FileHeader>\n'
        b'</Facturae>'
    )

    doc.embfile_add("facturae.xml", xml_content)

    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


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
def pdf_with_ubl_xml() -> BytesIO:
    """PDF con XML UBL embebido como archivo."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Factura UBL", fontname="helv")

    xml_content = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">\n'
        b'  <UBLExtensions>\n'
        b'    <UBLExtension>\n'
        b'      <ExtensionContent>cross-industry-invoice</ExtensionContent>\n'
        b'    </UBLExtension>\n'
        b'  </UBLExtensions>\n'
        b'</invoice>'
    )

    doc.embfile_add("invoice.xml", xml_content)

    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


class TestPyMuPdfEmbeddedXmlExtractor:
    """Tests para PyMuPdfEmbeddedXmlExtractor."""

    def get_extractor(self) -> PyMuPdfEmbeddedXmlExtractor:
        return PyMuPdfEmbeddedXmlExtractor()

    def test_extract_no_xml(self, pdf_without_xml: BytesIO):
        extractor = self.get_extractor()
        result = extractor.extract_embedded_xmls(pdf_without_xml)
        assert result == []

    def test_extract_facturae_xml(self, pdf_with_facturae_xml: BytesIO):
        extractor = self.get_extractor()
        result = extractor.extract_embedded_xmls(pdf_with_facturae_xml)
        assert len(result) >= 1
        xml_obj = result[0]
        assert xml_obj.format == XmlFormat.FACTURAE
        assert b"Facturae" in xml_obj.raw_xml or b"facturae" in xml_obj.raw_xml.lower()

    def test_extract_ubl_xml(self, pdf_with_ubl_xml: BytesIO):
        extractor = self.get_extractor()
        result = extractor.extract_embedded_xmls(pdf_with_ubl_xml)
        assert len(result) >= 1

    def test_detect_format_facturae(self):
        xml_content = (
            b'<?xml version="1.0"?>'
            b'<Facturae xmlns="http://www.facturae.es/Facturae/32">test</Facturae>'
        )
        fmt = PyMuPdfEmbeddedXmlExtractor.detect_format(xml_content)
        assert fmt == XmlFormat.FACTURAE

    def test_detect_format_ubl(self):
        xml_content = (
            b'<?xml version="1.0"?>'
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
            b'test</Invoice>'
        )
        fmt = PyMuPdfEmbeddedXmlExtractor.detect_format(xml_content)
        assert fmt == XmlFormat.UBL

    def test_detect_format_cii(self):
        xml_content = (
            b'<?xml version="1.0"?>'
            b'<CrossIndustryInvoice>test</CrossIndustryInvoice>'
        )
        fmt = PyMuPdfEmbeddedXmlExtractor.detect_format(xml_content)
        assert fmt == XmlFormat.CII

    def test_detect_format_zugferd(self):
        xml_content = (
            b'<?xml version="1.0"?>'
            b'<rsm:CrossIndustryDocumentContext>zugferd</rsm:CrossIndustryDocumentContext>'
        )
        fmt = PyMuPdfEmbeddedXmlExtractor.detect_format(xml_content)
        assert fmt == XmlFormat.CII

    def test_detect_format_unknown(self):
        xml_content = (
            b'<?xml version="1.0"?>'
            b'<someunknownformat>test</someunknownformat>'
        )
        fmt = PyMuPdfEmbeddedXmlExtractor.detect_format(xml_content)
        assert fmt == XmlFormat.UNKNOWN


class TestXmlFormat:
    """Tests para el enum XmlFormat."""

    def test_all_formats_have_string_values(self):
        for fmt in XmlFormat:
            assert isinstance(fmt.value, str)

    def test_facturae_value(self):
        assert XmlFormat.FACTURAE.value == "facturae"

    def test_ubl_value(self):
        assert XmlFormat.UBL.value == "ubl"

    def test_cii_value(self):
        assert XmlFormat.CII.value == "cii"

    def test_unknown_value(self):
        assert XmlFormat.UNKNOWN.value == "unknown"


class TestEmbeddedXml:
    """Tests para el dataclass EmbeddedXml."""

    def test_embedded_xml_creation(self):
        xml_obj = EmbeddedXml(
            raw_xml=b"<test>value</test>",
            format=XmlFormat.FACTURAE,
            filename="facturae.xml",
        )
        assert xml_obj.raw_xml == b"<test>value</test>"
        assert xml_obj.format == XmlFormat.FACTURAE
        assert xml_obj.filename == "facturae.xml"

    def test_embedded_xml_without_filename(self):
        xml_obj = EmbeddedXml(
            raw_xml=b"<test>value</test>",
            format=XmlFormat.UBL,
        )
        assert xml_obj.filename is None