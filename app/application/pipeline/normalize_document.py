"""Representación de documento normalizado para extracción.

El documento normalizado es la salida de la etapa de parsing/OCR/layout.
Todas las capas de extracción (texto digital, OCR, XML) producen este formato
antes de pasar a la extracción de candidatos.
"""

from dataclasses import dataclass, field
from enum import Enum


class ExtractionSource(str, Enum):
    """Fuente original del texto o dato."""

    DIGITAL_TEXT = "digital_text"
    OCR = "ocr"
    XML = "xml"
    VLM = "vlm"


@dataclass(frozen=True)
class NormalizedBlock:
    """Bloque de texto normalizado con coordenadas y metadatos."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page: int
    source: ExtractionSource
    confidence: float = 1.0  # 0.0-1.0; para DIGITAL_TEXT vale 1.0


@dataclass(frozen=True)
class NormalizedPage:
    """Página con bloques normalizados."""

    page_number: int
    blocks: list[NormalizedBlock] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Texto completo concatenado."""
        return "\n".join(b.text for b in self.blocks)


@dataclass(frozen=True)
class NormalizedDocument:
    """Documento normalizado listo para extracción de candidatos.

    Es la representación intermedia entre el parsing/OCR y la extracción
    de campos. Se produce una vez por documento y se consume en la etapa
    de candidatos.
    """

    pages: list[NormalizedPage] = field(default_factory=list)
    source: ExtractionSource = ExtractionSource.DIGITAL_TEXT

    @property
    def all_blocks(self) -> list[NormalizedBlock]:
        """Todos los bloques ordenados por página."""
        return [block for page in self.pages for block in page.blocks]

    @property
    def full_text(self) -> str:
        """Texto completo del documento."""
        return "\n\n".join(page.full_text for page in self.pages)