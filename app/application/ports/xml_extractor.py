"""Puerto para lectura de XML embebido en PDFs."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from io import BytesIO


class XmlFormat(str, Enum):
    """Formato XML detectado."""

    FACTURAE = "facturae"
    UBL = "ubl"
    CII = "cii"  # Factur-X / ZUGFeRD
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EmbeddedXml:
    """XML embebido extraído del PDF."""

    raw_xml: bytes
    format: XmlFormat
    filename: str | None = None


class EmbeddedXmlExtractor(ABC):
    """Puerto abstracto para extraer XML embebido de un PDF."""

    @abstractmethod
    def extract_embedded_xmls(
        self, pdf_source: BytesIO | str
    ) -> list[EmbeddedXml]:
        """Extrae todos los XML embebidos en el PDF.

        Devuelve lista vacía si no hay ninguno.
        """

    @abstractmethod
    def detect_format(xml_content: bytes) -> XmlFormat:
        """Detecta el formato del XML."""