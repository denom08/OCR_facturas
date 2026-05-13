"""Extractor de XML embebido usando PyMuPDF.

PyMuPDF 1.27+ soporta embfile_names() y embfile_info() para extraer
archivos embebidos en un PDF (incluidos XML de facturas electrónicas).
No se necesita pikepdf ni pypdf adicional.
"""

from io import BytesIO

import fitz  # PyMuPDF

from app.application.ports.xml_extractor import (
    EmbeddedXml,
    EmbeddedXmlExtractor,
    XmlFormat,
)


class PyMuPdfEmbeddedXmlExtractor(EmbeddedXmlExtractor):
    """Implementación de EmbeddedXmlExtractor usando PyMuPDF.

    PyMuPDF 1.24+ soporta embebed files extraction via embfile_names() /
    embfile_info() / extract_image().
    """

    def extract_embedded_xmls(
        self, pdf_source: BytesIO | str
    ) -> list[EmbeddedXml]:
        """Extrae todos los XML embebidos en el PDF."""
        doc = self._open(pdf_source)
        try:
            xmls: list[EmbeddedXml] = []
            for name in doc.embfile_names():
                info = doc.embfile_info(name)
                if info and info.get("name", "").strip().lower().endswith(".xml"):
                    try:
                        raw = doc.embfile_get(name)
                        fmt = self.detect_format(raw)
                        xmls.append(
                            EmbeddedXml(
                                raw_xml=raw,
                                format=fmt,
                                filename=info.get("name"),
                            )
                        )
                    except Exception:
                        pass
            return xmls
        finally:
            doc.close()

    @staticmethod
    def detect_format(xml_content: bytes) -> XmlFormat:
        """Detecta el formato del XML por su contenido raíz."""
        try:
            text = xml_content[: 4 * 1024].decode("utf-8", errors="ignore").strip()
        except Exception:
            return XmlFormat.UNKNOWN

        text_lower = text.lower()

        if "<facturae" in text_lower:
            return XmlFormat.FACTURAE
        if "<invoice" in text_lower and "xmlns" in text_lower and (
            "ubl" in text_lower or "un-cefact" in text_lower
        ):
            return XmlFormat.UBL
        if "cross-industry-invoice" in text_lower or "zugferd" in text_lower:
            return XmlFormat.CII
        if "<crossindustryinvoice" in text_lower:
            return XmlFormat.CII
        if "<rsm" in text_lower and "documentcontext" in text_lower:
            return XmlFormat.CII

        return XmlFormat.UNKNOWN

    def _open(self, pdf_source: BytesIO | str) -> fitz.Document:
        """Abre el PDF desde BytesIO o path."""
        if isinstance(pdf_source, str):
            return fitz.open(pdf_source)
        pdf_source.seek(0)
        data = pdf_source.read() if hasattr(pdf_source, "read") else pdf_source
        return fitz.open(stream=data)