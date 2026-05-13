"""Tests para el adaptador PyMuPDF y el puerto PdfReader."""

from io import BytesIO

import fitz
import pytest
from PIL import Image

from app.application.ports.pdf_reader import ImageInfo, PdfKind, TextBlock
from app.infrastructure.pdf import PyMuPdfReader

# ---------------------------------------------------------------------------
# Fixtures: PDFs sintéticos mínimo
# ---------------------------------------------------------------------------


@pytest.fixture
def pdf_digital() -> BytesIO:
    """PDF completamente digital con texto extraíble."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "FACTURA 2024/001", fontname="helv")
    page.insert_text((50, 80), "Proveedor Test S.L.  B12345678", fontname="helv")
    page.insert_text((50, 110), "Cliente Test S.A.  A87654321", fontname="helv")
    page.insert_text((50, 150), "Base: 100,00 euros", fontname="helv")
    page.insert_text((50, 170), "IVA 21%: 21,00 euros", fontname="helv")
    page.insert_text((50, 190), "TOTAL: 121,00 euros", fontname="helv")
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


@pytest.fixture
def pdf_with_image() -> BytesIO:
    """PDF híbrido: poco texto y una imagen."""
    doc = fitz.open()
    page = doc.new_page()
    # Texto mínimo
    page.insert_text((50, 50), "FACTURA", fontname="helv")
    # Crear una imagen PNG mínima (1x1 pixel) y embeberla
    img_data = BytesIO()
    Image.new("RGB", (10, 10), color="red").save(img_data, "PNG")
    img_data.seek(0)
    page.insert_image(fitz.Rect(50, 80, 150, 180), stream=img_data.read())
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


@pytest.fixture
def pdf_empty() -> BytesIO:
    """PDF escaneado: sin texto, sin imágenes (página vacía)."""
    doc = fitz.open()
    doc.new_page()  # página sin contenido
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


@pytest.fixture
def pdf_embedded_xml() -> BytesIO:
    """PDF con XML embebido tipo Facturae (detectado en texto de página)."""
    doc = fitz.open()
    page = doc.new_page()
    # Simular texto que contiene indicadores de XML embebido
    page.insert_text(
        (50, 50), '<?xml version="1.0"?><facturae>test</facturae>', fontname="helv"
    )
    buf = BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Tests: PyMuPdfReader
# ---------------------------------------------------------------------------


class TestPyMuPdfReader:
    """Tests para la clase PyMuPdfReader."""

    def get_reader(self) -> PyMuPdfReader:
        return PyMuPdfReader()

    def test_page_count_digital(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        assert reader.page_count(pdf_digital) == 1

    def test_page_count_multiple_pages(self):
        doc = fitz.open()
        doc.new_page()
        doc.new_page()
        buf = BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)
        reader = self.get_reader()
        assert reader.page_count(buf) == 2

    def test_extract_text_by_page_digital(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        result = reader.extract_text_by_page(pdf_digital)
        assert 1 in result
        text = result[1]
        assert "FACTURA" in text
        assert "Proveedor Test" in text
        assert "B12345678" in text

    def test_extract_text_by_page_empty(self, pdf_empty: BytesIO):
        reader = self.get_reader()
        result = reader.extract_text_by_page(pdf_empty)
        assert 1 in result
        assert result[1].strip() == ""

    def test_extract_text_blocks_digital(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        blocks = reader.extract_text_blocks(pdf_digital)
        assert len(blocks) > 0
        for block in blocks:
            assert isinstance(block, TextBlock)
            assert block.page == 1
            assert block.bbox is not None
            x0, y0, x1, y1 = block.bbox
            assert x1 > x0
            assert y1 > y0

    def test_extract_text_blocks_empty(self, pdf_empty: BytesIO):
        reader = self.get_reader()
        blocks = reader.extract_text_blocks(pdf_empty)
        # PDF vacío puede tener un bloque vacío
        assert isinstance(blocks, list)

    def test_detect_images_digital(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        images = reader.detect_images(pdf_digital)
        assert isinstance(images, list)

    def test_detect_images_with_image(self, pdf_with_image: BytesIO):
        reader = self.get_reader()
        images = reader.detect_images(pdf_with_image)
        assert len(images) >= 1
        assert images[0].page == 1
        assert images[0].width > 0
        assert images[0].height > 0

    def test_detect_images_empty(self, pdf_empty: BytesIO):
        reader = self.get_reader()
        images = reader.detect_images(pdf_empty)
        assert images == []

    def test_render_page_to_image(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        img_buf = reader.render_page_to_image(pdf_digital, page_number=1, dpi=72)
        assert img_buf is not None
        assert img_buf.getbuffer().nbytes > 0
        # Validar que es PNG
        img_buf.seek(0)
        header = img_buf.read(8)
        assert header[:4] == b"\x89PNG"

    def test_render_page_invalid_page_raises(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        with pytest.raises(IndexError):
            reader.render_page_to_image(pdf_digital, page_number=99)

    def test_classify_digital(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        assert reader.classify(pdf_digital) == PdfKind.DIGITAL

    def test_classify_scanned(self, pdf_empty: BytesIO):
        reader = self.get_reader()
        assert reader.classify(pdf_empty) == PdfKind.SCANNED

    def test_classify_embedded_xml(self, pdf_embedded_xml: BytesIO):
        reader = self.get_reader()
        assert reader.classify(pdf_embedded_xml) == PdfKind.EMBEDDED_XML

    def test_has_embedded_xml_false(self, pdf_digital: BytesIO):
        reader = self.get_reader()
        assert reader.has_embedded_xml(pdf_digital) is False

    def test_has_embedded_xml_true(self, pdf_embedded_xml: BytesIO):
        reader = self.get_reader()
        assert reader.has_embedded_xml(pdf_embedded_xml) is True

    def test_classify_hybrid(self, pdf_with_image: BytesIO):
        reader = self.get_reader()
        kind = reader.classify(pdf_with_image)
        # Poco texto + imagen -> híbrido
        assert kind in (PdfKind.HYBRID, PdfKind.SCANNED)


class TestPdfKind:
    """Tests para el enum PdfKind."""

    def test_all_kinds_have_string_values(self):
        for kind in PdfKind:
            assert isinstance(kind.value, str)
            assert kind.value in ("digital", "hybrid", "scanned", "embedded_xml")


class TestTextBlock:
    """Tests para el dataclass TextBlock."""

    def test_text_block_creation(self):
        block = TextBlock(text="Hello", bbox=(0, 0, 100, 50), page=1)
        assert block.text == "Hello"
        assert block.bbox == (0, 0, 100, 50)
        assert block.page == 1

    def test_text_block_immutable(self):
        block = TextBlock(text="Hello", bbox=(0, 0, 100, 50), page=1)
        with pytest.raises((TypeError, AttributeError)):  # frozen dataclass
            block.text = "Changed"


class TestImageInfo:
    """Tests para el dataclass ImageInfo."""

    def test_image_info_creation(self):
        img = ImageInfo(page=1, width=800, height=600)
        assert img.page == 1
        assert img.width == 800
        assert img.height == 600
        assert img.bbox is None

    def test_image_info_with_bbox(self):
        img = ImageInfo(page=1, width=800, height=600, bbox=(10, 20, 100, 200))
        assert img.bbox == (10, 20, 100, 200)