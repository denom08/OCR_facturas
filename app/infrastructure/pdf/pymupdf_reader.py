"""Adaptador PdfReader basado en PyMuPDF."""

from io import BytesIO

import fitz  # PyMuPDF

from app.application.ports.pdf_reader import (
    ImageInfo,
    PdfKind,
    PdfReader,
    TextBlock,
)


class PyMuPdfReader(PdfReader):
    """Implementación de PdfReader usando PyMuPDF."""

    def _open(self, pdf_source: BytesIO | str) -> fitz.Document:
        """Abre el PDF desde BytesIO o path."""
        if isinstance(pdf_source, str):
            return fitz.open(pdf_source)
        # BytesIO o bytes
        pdf_source.seek(0)
        data = pdf_source.read() if hasattr(pdf_source, "read") else pdf_source
        return fitz.open(stream=data)

    def page_count(self, pdf_source: BytesIO | str) -> int:
        doc = self._open(pdf_source)
        try:
            return doc.page_count
        finally:
            doc.close()

    def extract_text_by_page(self, pdf_source: BytesIO | str) -> dict[int, str]:
        doc = self._open(pdf_source)
        try:
            result: dict[int, str] = {}
            for page_num in range(doc.page_count):
                page = doc[page_num]
                result[page_num + 1] = page.get_text("text")
            return result
        finally:
            doc.close()

    def extract_text_blocks(
        self, pdf_source: BytesIO | str
    ) -> list[TextBlock]:
        doc = self._open(pdf_source)
        try:
            blocks: list[TextBlock] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                raw_blocks = page.get_text("blocks")
                for raw in raw_blocks:
                    if len(raw) >= 6 and raw[4].strip():
                        x0, y0, x1, y1 = raw[0], raw[1], raw[2], raw[3]
                        blocks.append(TextBlock(
                            text=raw[4],
                            bbox=(x0, y0, x1, y1),
                            page=page_num + 1,
                        ))
            return blocks
        finally:
            doc.close()

    def detect_images(self, pdf_source: BytesIO | str) -> list[ImageInfo]:
        doc = self._open(pdf_source)
        try:
            images: list[ImageInfo] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                image_list = page.get_images(full=True)
                for img in image_list:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    width = base_image["width"]
                    height = base_image["height"]
                    img_bbox: tuple[float, float, float, float] | None = None
                    try:
                        img_info = page.get_image_info(xrefs=[xref])
                        if img_info and len(img_info) > 0:
                            img_bbox = tuple(img_info[0]["bbox"])
                    except Exception:
                        pass
                    images.append(ImageInfo(
                        page=page_num + 1,
                        width=width,
                        height=height,
                        bbox=img_bbox,
                    ))
            return images
        finally:
            doc.close()

    def render_page_to_image(
        self, pdf_source: BytesIO | str, page_number: int, dpi: int = 150
    ) -> BytesIO:
        doc = self._open(pdf_source)
        try:
            page = doc[page_number - 1]  # 1-indexed en la API
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            clip = page.rect
            pix = page.get_pixmap(matrix=mat, clip=clip)
            return BytesIO(pix.tobytes("png"))
        finally:
            doc.close()

    def classify(self, pdf_source: BytesIO | str) -> PdfKind:
        if self.has_embedded_xml(pdf_source):
            return PdfKind.EMBEDDED_XML

        doc = self._open(pdf_source)
        try:
            total_text_len = 0
            total_images = 0

            for page_num in range(doc.page_count):
                page = doc[page_num]
                text = page.get_text("text")
                total_text_len += len(text.strip())
                total_images += len(page.get_images(full=True))

            # SCANNED: sin texto extractable y con imágenes (o página vacía)
            if total_text_len == 0:
                return PdfKind.SCANNED

            # HYBRID: texto mínimo (poco extractable) + imágenes presentes
            # Un documento escaneado con OCR rápido puede tener texto limitado
            # junto con imágenes de fondo.
            if total_text_len < 50 and total_images > 0:
                return PdfKind.HYBRID

            # DIGITAL: suficiente texto extractable, puede tener o no imágenes
            return PdfKind.DIGITAL
        finally:
            doc.close()

    def has_embedded_xml(self, pdf_source: BytesIO | str) -> bool:
        doc = self._open(pdf_source)
        try:
            for page_num in range(doc.page_count):
                page = doc[page_num]
                get_text = page.get_text("text")
                if "<?xml" in get_text or "<facturae" in get_text.lower() or \
                   "<ubl" in get_text.lower() or "<cii" in get_text.lower():
                    return True
            # Revisar archivos embebidos (PyMuPDF 1.27+ API)
            try:
                for name in doc.embfile_names():
                    info = doc.embfile_info(name)
                    if info and "xml" in info.get("name", "").lower():
                        return True
            except Exception:
                pass
            return False
        finally:
            doc.close()