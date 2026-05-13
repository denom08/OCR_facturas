"""Adaptador PaddleOCR para extracción de texto en PDFs escaneados.

Este adaptador es LAZY: no carga modelos ni verifica dependencias hasta que
process_image() es llamado por primera vez. Esto permite que el proyecto
arranque sin PaddleOCR instalado y que los tests funcionen sin GPU/modelos.

PaddleOCR se instala como dependencia opcional:

    pip install ocr-facturas[paddleocr]

En Windows con GPU NVIDIA, PaddlePaddle se instala con:

    pip install paddlepaddle-gpu

Sin GPU, usar:

    pip install paddlepaddle

El modelo se descarga automáticamente en el primer uso (~40MB para det+rec).
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import TYPE_CHECKING

from app.application.ports.ocr_engine import (
    OcrBlock,
    OcrEngine,
    OcrResult,
    OcrUnavailableError,
)

if TYPE_CHECKING:
    from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)


class PaddleOcrEngine(OcrEngine):
    """Implementación de OcrEngine usando PaddleOCR.

    Soporta CPU y GPU (NVIDIA). Si PaddleOCR o PaddlePaddle no están
    instalados, is_available() devuelve False y no crashea.

    Uso típico::

        engine = PaddleOcrEngine()
        if engine.is_available():
            result = engine.process_image(image_bytes)
        else:
            # Usar respuesta controlada con warning
            ...
    """

    def __init__(
        self,
        *,
        use_angle_cls: bool = True,
        lang: str = "es,en",
        use_gpu: bool = False,
        show_log: bool = False,
    ) -> None:
        """Configura el motor OCR.

        Args:
            use_angle_cls: Usar clasificación de ángulo (mejora en textos rotados).
            lang: Idiomas训练的模型 (''). Por defecto español + inglés.
            use_gpu: Usar GPU NVIDIA si está disponible.
            show_log: Mostrar logs de PaddleOCR.
        """
        self._use_angle_cls = use_angle_cls
        self._lang = lang
        self._use_gpu = use_gpu
        self._show_log = show_log
        self._engine: PaddleOCR | None = None

    # ------------------------------------------------------------------
    # Lazy init: no cargar el modelo hasta que sea necesario
    # ------------------------------------------------------------------

    def _get_engine(self) -> PaddleOCR:
        """Carga perezosa del motor PaddleOCR (modelos + OCR)."""
        if self._engine is None:
            from paddleocr import PaddleOCR

            logger.info(
                "Inicializando PaddleOCR (lang=%s, use_gpu=%s, lazy)",
                self._lang,
                self._use_gpu,
            )
            self._engine = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=self._show_log,
            )
        return self._engine

    # ------------------------------------------------------------------
    # OcrEngine interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Comprueba si PaddleOCR y PaddlePaddle están instalados."""
        try:
            from paddleocr import PaddleOCR  # noqa: F401
            from paddlepaddle import paddle  # noqa: F401
            return True
        except ImportError:
            return False

    def name(self) -> str:
        return "PaddleOCR"

    def process_image(self, image_data: BytesIO, page: int = 1) -> OcrResult:
        """Ejecuta OCR sobre una imagen usando PaddleOCR.

        Args:
            image_data: Imagen en formato PNG/JPEG como BytesIO.
            page: Número de página para evidencias.

        Returns:
            OcrResult con bloques detectados, coordenadas y confianza.

        Raises:
            OcrUnavailableError: si PaddleOCR/PaddlePaddle no están disponibles.
        """
        if not self.is_available():
            raise OcrUnavailableError(
                "PaddleOCR no está disponible. "
                "Instala con: pip install ocr-facturas[paddleocr]"
            )

        # Leer bytes de la imagen para PaddleOCR
        image_bytes = image_data.read()
        image_data.seek(0)

        engine = self._get_engine()
        result = engine.ocr(image_bytes, cls=self._use_angle_cls)

        blocks: list[OcrBlock] = []
        if result and result[0]:
            for line in result[0]:
                if line:
                    # PaddleOCR devuelve: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]], texto, confianza
                    coords = line[0]
                    text = line[1][0]
                    confidence = float(line[1][1])

                    # Extraer bbox: (x0, y0, x1, y1)
                    if len(coords) == 4:
                        xs = [p[0] for p in coords]
                        ys = [p[1] for p in coords]
                        bbox = (min(xs), min(ys), max(xs), max(ys))
                    else:
                        bbox = (0.0, 0.0, 0.0, 0.0)

                    blocks.append(
                        OcrBlock(
                            text=text,
                            bbox=bbox,
                            confidence=confidence,
                        )
                    )

        return OcrResult(
            blocks=blocks,
            page=page,
            engine="paddleocr",
        )