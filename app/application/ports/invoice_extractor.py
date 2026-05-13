"""Puerto abstracto para extractores IA / VLM (B9).

El VLM local se usa como APOYO, no como fuente de verdad. Solo propone
candidatos/valores que deben pasar por los validadores de dominio (B2) y
el resolutor de campos (B8) antes de aceptarse.

Responsabilidades del puerto:
1. Definir interfaz mínima para enviar imagen/página + prompt al VLM.
2. Devolver la respuesta parseada o un error controlado.
3. El VLM puede estar o no disponible — nunca crashea la API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from io import BytesIO


@dataclass(frozen=True)
class VlmRawResponse:
    """Respuesta cruda del VLM antes de parsear."""

    raw_text: str
    model: str
    latency_ms: float
    tokens_used: int | None = None


@dataclass
class VlmExtractedField:
    """Un campo extraído por el VLM con metadatos."""

    field_name: str
    value: str
    confidence: float = 1.0
    page: int = 1
    bbox: tuple[float, float, float, float] | None = None
    reasoning: str | None = None


@dataclass
class VlmExtractionResult:
    """Resultado de la extracción VLM para una página o documento."""

    fields: list[VlmExtractedField] = field(default_factory=list)
    raw_response: VlmRawResponse | None = None
    warning: str | None = None  # e.g. "model output malformed, falling back to null"

    @property
    def extracted_dict(self) -> dict[str, str]:
        """Dict field_name -> value para consumo por pipeline."""
        return {f.field_name: f.value for f in self.fields}

    def get(self, field_name: str, default: str | None = None) -> str | None:
        return next((f.value for f in self.fields if f.field_name == field_name), default)


class InvoiceExtractor(ABC):
    """Puerto abstracto para extractores IA/VLM.

    Los adaptadores concretos (Qwen2.5-VL via vLLM/Transformers, etc.)
    implementan este puerto. El sistema puede funcionar sin VLM instalado —
    en ese caso, is_available() devuelve False.

    Diseño LAZY: no carga modelos hasta la primera llamada a extract().
    Esto permite que pytest funcione sin GPU ni modelos pesados.

    El VLM SOLO propone candidatos. El dominio (B2) y el resolutor (B8)
    validan y deciden si se aceptan los valores.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el extractor VLM está disponible en este entorno.

        Returns:
            True si el motor VLM y sus dependencias están instalados.
            False si no están disponibles (por ejemplo, sin GPU ni modelo).
        """

    @abstractmethod
    def name(self) -> str:
        """Nombre del extractor VLM para logging y debug."""

    @abstractmethod
    def model_id(self) -> str:
        """Identificador del modelo usado (e.g. Qwen2.5-VL-7B-Instruct)."""

    @abstractmethod
    def extract(
        self,
        image_data: BytesIO,
        page: int = 1,
        prompt: str | None = None,
    ) -> VlmExtractionResult:
        """Envía una página al VLM y devuelve campos extraídos.

        Args:
            image_data: Imagen de la página en formato PNG/JPEG/etc. como BytesIO.
            page: Número de página para logging y evidencias.
            prompt: Prompt override. Si es None, usa el prompt por defecto.

        Returns:
            VlmExtractionResult con campos propuestos y metadatos.
            Si el modelo no puede procesar la imagen, devuelve result con
            warning y campos vacíos (no lanza excepción).

        Raises:
            VlmUnavailableError: si el extractor no está disponible.
        """

    def extract_multi_page(
        self,
        images: list[BytesIO],
        prompt: str | None = None,
    ) -> list[VlmExtractionResult]:
        """Procesa múltiples páginas secuencialmente.

        Por defecto itera sobre extract(). Los adaptadores pueden
        optimizar esto con batch processing si el backend lo soporta.
        """
        return [self.extract(img, page=i + 1, prompt=prompt) for i, img in enumerate(images)]


class VlmUnavailableError(RuntimeError):
    """Se intentó usar el VLM pero no está disponible."""


class VlmParseError(RuntimeError):
    """El VLM devolvió texto que no pudo parsearse como JSON."""