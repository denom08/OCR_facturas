"""Puerto para lectura de documentos PDF."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from io import BytesIO


class PdfKind(str, Enum):
    """Clasificación del tipo de documento PDF."""

    DIGITAL = "digital"  # Texto extraíble abundante
    HYBRID = "hybrid"  # Poco texto, muchas imágenes
    SCANNED = "scanned"  # Prácticamente sin texto
    EMBEDDED_XML = "embedded_xml"  # XML embebido (Facturae/UBL/CII)


@dataclass(frozen=True)
class TextBlock:
    """Bloque de texto con coordenadas."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page: int


@dataclass(frozen=True)
class ImageInfo:
    """Información sobre una imagen detectada en el PDF."""

    page: int
    width: int
    height: int
    bbox: tuple[float, float, float, float] | None = None


class PdfReader(ABC):
    """Puerto abstracto para leer PDFs."""

    @abstractmethod
    def page_count(self, pdf_source: BytesIO | str) -> int:
        """Devuelve el número de páginas del PDF."""

    @abstractmethod
    def extract_text_by_page(
        self, pdf_source: BytesIO | str
    ) -> dict[int, str]:
        """Extrae texto por página. Clave: número de página (1-indexed)."""

    @abstractmethod
    def extract_text_blocks(
        self, pdf_source: BytesIO | str
    ) -> list[TextBlock]:
        """Extrae bloques de texto con coordenadas si están disponibles."""

    @abstractmethod
    def detect_images(self, pdf_source: BytesIO | str) -> list[ImageInfo]:
        """Detecta imágenes por página."""

    @abstractmethod
    def render_page_to_image(
        self, pdf_source: BytesIO | str, page_number: int, dpi: int = 150
    ) -> BytesIO:
        """Renderiza una página a imagen PNG."""

    @abstractmethod
    def classify(self, pdf_source: BytesIO | str) -> PdfKind:
        """Clasifica el PDF según su tipo."""

    @abstractmethod
    def has_embedded_xml(self, pdf_source: BytesIO | str) -> bool:
        """Detecta si hay XML embebido en el PDF."""