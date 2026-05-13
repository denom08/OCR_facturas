"""Puerto abstracto para motores OCR."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from io import BytesIO


@dataclass(frozen=True)
class OcrBlock:
    """Bloque de texto detectado por OCR con coordenadas y confianza."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    confidence: float  # 0.0 - 1.0


@dataclass
class OcrResult:
    """Resultado de una pasada de OCR sobre una imagen."""

    blocks: list[OcrBlock] = field(default_factory=list)
    page: int = 1
    engine: str = "unknown"

    @property
    def full_text(self) -> str:
        """Texto completo concatenado."""
        return "\n".join(b.text for b in self.blocks)


class OcrEngine(ABC):
    """Puerto abstracto para motores OCR.

    Los adaptadores concretos (PaddleOCR, Tesseract, etc.) implementan este puerto.
    El sistema puede funcionar sin motor OCR instalado — en ese caso,
    OcrEngine.is_available() devuelve False y el pipeline responde con warning
    controlado en lugar de crashear.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el motor OCR está disponible en este entorno.

        Returns:
            True si el motor y sus dependencias están instaladas.
            False si no están disponibles (por ejemplo, PaddleOCR sin GPU/models).
        """

    @abstractmethod
    def name(self) -> str:
        """Nombre del motor OCR para logging y debug."""

    @abstractmethod
    def process_image(self, image_data: BytesIO, page: int = 1) -> OcrResult:
        """Ejecuta OCR sobre una imagen.

        Args:
            image_data: Imagen en formato PNG/JPEG/etc. como BytesIO.
            page: Número de página asociado (para evidencias).

        Returns:
            OcrResult con los bloques detectados y su confianza.

        Raises:
            OcrUnavailableError: si el motor no está disponible (is_available=False).
        """

    def process_pdf_page(
        self, pdf_source: BytesIO | str, page_number: int, dpi: int = 150
    ) -> OcrResult:
        """Renderiza una página PDF a imagen y ejecuta OCR.

        Por defecto usa el renderizado de PdfReader. Los adaptadores pueden
        optimizar esto si tienen su propio renderizado.
        """
        from app.infrastructure.pdf import PyMuPdfReader

        reader = PyMuPdfReader()
        image_data = reader.render_page_to_image(pdf_source, page_number, dpi)
        return self.process_image(image_data, page=page_number)


class OcrUnavailableError(RuntimeError):
    """Se intentó usar OCR pero el motor no está disponible."""