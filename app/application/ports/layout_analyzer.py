"""Puerto abstracto para análisis de layout y tablas."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LayoutEngineKind(str, Enum):
    """Tipo de motor de layout."""

    PP_STRUCTURE_V3 = "pp_structure_v3"
    DOCLING = "docling"
    PADDLE_STRUCTURE = "paddle_structure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LayoutCell:
    """Celda individual dentro de una tabla detectada."""

    text: str
    row: int
    col: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page: int
    confidence: float = 1.0  # 0.0-1.0


@dataclass(frozen=True)
class LayoutTable:
    """Tabla detectada con celdas, índice de página y bbox global."""

    cells: list[LayoutCell] = field(default_factory=list)
    page: int = 1
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    rows: int = 0
    cols: int = 0
    confidence: float = 0.0
    kind: str = "unknown"  # e.g. "tax_table", "line_items", "unknown"


@dataclass(frozen=True)
class LayoutResult:
    """Resultado completo del análisis de layout de una página."""

    tables: list[LayoutTable] = field(default_factory=list)
    page: int = 1
    engine: str = "unknown"
    raw: Any = None  # datos nativos del motor para debug


class LayoutAnalyzer(ABC):
    """Puerto abstracto para motores de análisis de layout y tablas.

    Los adaptadores concretos (PP-StructureV3, Docling, etc.) implementan
    este puerto. El sistema puede funcionar sin motor de layout instalado —
    en ese caso, is_available() devuelve False y el pipeline responde con
    warning controlado en lugar de crashear.

    El diseño es LAZY: no carga modelos hasta la primera llamada a
    process_page(). Esto permite que pytest funcione sin GPU ni modelos
    pesados y que la API arranque aunque PP-StructureV3 no esté instalado.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el motor de layout está disponible en este entorno.

        Returns:
            True si el motor y sus dependencias están instaladas.
            False si no están disponibles (por ejemplo, PP-StructureV3 sin GPU).
        """

    @abstractmethod
    def name(self) -> str:
        """Nombre del motor para logging y debug."""

    @abstractmethod
    def kind(self) -> LayoutEngineKind:
        """Tipo de motor."""

    @abstractmethod
    def process_page(self, image_data: Any, page: int = 1) -> LayoutResult:
        """Analiza el layout de una página (imagen PNG/JPEG/etc.).

        Args:
            image_data: Imagen en formato PNG/JPEG/etc. como BytesIO o similar.
            page: Número de página asociado (para evidencias).

        Returns:
            LayoutResult con las tablas detectadas, celdas y coordenadas.

        Raises:
            LayoutUnavailableError: si el motor no está disponible.
        """

    def process_pdf_page(self, pdf_source: Any, page_number: int, dpi: int = 150) -> LayoutResult:
        """Renderiza una página PDF a imagen y ejecuta análisis de layout.

        Por defecto usa el renderizado de PdfReader. Los adaptadores pueden
        optimizar esto si tienen su propio renderizado.
        """
        from app.infrastructure.pdf import PyMuPdfReader

        reader = PyMuPdfReader()
        image_data = reader.render_page_to_image(pdf_source, page_number, dpi)
        return self.process_page(image_data, page=page_number)


class LayoutUnavailableError(RuntimeError):
    """Se intentó usar layout analysis pero el motor no está disponible."""