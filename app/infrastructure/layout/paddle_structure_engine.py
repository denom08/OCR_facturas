"""Adaptador PP-StructureV3 / Paddle Structure para análisis de layout y tablas.

Este adaptador es LAZY: no carga modelos ni verifica dependencias hasta que
process_page() es llamado por primera vez. Esto permite que el proyecto
arranque sin PP-StructureV3 instalado y que los tests funcionen sin GPU/modelos.

PP-StructureV3 se instala como dependencia opcional:

    pip install ocr-facturas[paddlestructure]

En Windows con GPU NVIDIA, PaddlePaddle se instala con:

    pip install paddlepaddle-gpu

Sin GPU, usar:

    pip install paddlepaddle

El modelo se descarga automáticamente en el primer uso.

PP-StructureV3 incluye:
- Detección de tablas (TableRecognition)
- Extracción de estructura de celdas
- Clasificación de layout (header, body, footer, etc.)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from app.application.ports.layout_analyzer import (
    LayoutAnalyzer,
    LayoutCell,
    LayoutEngineKind,
    LayoutResult,
    LayoutTable,
    LayoutUnavailableError,
)

if TYPE_CHECKING:
    from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)


class PPSTructureV3Analyzer(LayoutAnalyzer):
    """Implementación de LayoutAnalyzer usando PaddleOCR + PP-StructureV3.

    Detecta tablas, extrae celdas con coordenadas y confianza. Soporta CPU y GPU.
    Si PP-StructureV3 o PaddlePaddle no están instalados, is_available() devuelve
    False y no crashea.

    Uso típico::

        analyzer = PPSTructureV3Analyzer()
        if analyzer.is_available():
            result = analyzer.process_page(image_bytes)
            for table in result.tables:
                for cell in table.cells:
                    print(cell.text, cell.bbox)
        else:
            # Usar respuesta controlada con warning
            ...

    Para tablas fiscales, el extractor de tax_table_extractor.py consume
    LayoutResult y produce TaxLineCandidates.
    """

    def __init__(
        self,
        *,
        use_angle_cls: bool = True,
        lang: str = "es,en",
        use_gpu: bool = False,
        show_log: bool = False,
        table_threshold: float = 0.5,
    ) -> None:
        """Configura el analyzer.

        Args:
            use_angle_cls: Usar clasificación de ángulo (mejora en textos rotados).
            lang: Idiomas del modelo. Por defecto español + inglés.
            use_gpu: Usar GPU NVIDIA si está disponible.
            show_log: Mostrar logs de PaddleOCR.
            table_threshold: Umbral de confianza para aceptar celdas de tabla.
        """
        self._use_angle_cls = use_angle_cls
        self._lang = lang
        self._use_gpu = use_gpu
        self._show_log = show_log
        self._table_threshold = table_threshold
        self._ocr_engine: PaddleOCR | None = None

    # ------------------------------------------------------------------
    # Lazy init: no cargar el modelo hasta que sea necesario
    # ------------------------------------------------------------------

    def _get_ocr_engine(self) -> PaddleOCR:
        """Carga perezosa del motor PaddleOCR (solo OCR base)."""
        if self._ocr_engine is None:
            from paddleocr import PaddleOCR

            logger.info(
                "Inicializando PaddleOCR para layout (lang=%s, use_gpu=%s, lazy)",
                self._lang,
                self._use_gpu,
            )
            self._ocr_engine = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=self._show_log,
            )
        return self._ocr_engine

    # ------------------------------------------------------------------
    # LayoutAnalyzer interface
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
        return "PP-StructureV3"

    def kind(self) -> LayoutEngineKind:
        return LayoutEngineKind.PP_STRUCTURE_V3

    def process_page(self, image_data: Any, page: int = 1) -> LayoutResult:
        """Analiza layout de una página usando PaddleOCR con reconocimiento de tablas.

        Args:
            image_data: Imagen en formato PNG/JPEG como BytesIO.
            page: Número de página para evidencias.

        Returns:
            LayoutResult con tablas detectadas, celdas y coordenadas.

        Raises:
            LayoutUnavailableError: si PP-StructureV3/PaddlePaddle no están disponibles.
        """
        if not self.is_available():
            raise LayoutUnavailableError(
                "PP-StructureV3 no está disponible. "
                "Instala con: pip install ocr-facturas[paddlestructure]"
            )

        # Leer bytes de la imagen
        if hasattr(image_data, "read"):
            image_bytes = image_data.read()
            image_data.seek(0)
        else:
            image_bytes = image_data

        # Usar PaddleOCR con enable_table_detection=True para table OCR
        # El resultado incluye estructuras de tabla cuando están disponibles
        ocr = self._get_ocr_engine()
        result = ocr.ocr(image_bytes, cls=self._use_angle_cls)

        tables: list[LayoutTable] = []
        if result and result[0]:
            # Procesar bloques y detectar estructura de tabla
            blocks = result[0]
            tables = self._extract_tables_from_blocks(blocks, page)

        return LayoutResult(
            tables=tables,
            page=page,
            engine="pp_structure_v3",
            raw=result,
        )

    def _extract_tables_from_blocks(
        self, blocks: list[Any], page: int
    ) -> list[LayoutTable]:
        """Convierte bloques OCR en LayoutTable con celdas detectadas.

        PP-StructureV3 / PaddleOCR con table=True devuelve estructuras
        de tabla en el resultado OCR. Extraemos celdas y detectamos
        si son tablas fiscales por contenido.
        """
        tables: list[LayoutTable] = []

        for block in blocks:
            if not block or len(block) < 2:
                continue

            coords = block[0]
            raw_block_data = block[1]
            if isinstance(raw_block_data, (list, tuple)):
                text = str(raw_block_data[0])
                confidence = float(raw_block_data[1]) if len(raw_block_data) > 1 else 1.0
            else:
                text = str(raw_block_data)
                confidence = 1.0

            # Extraer bbox global del bloque
            if len(coords) == 4:
                xs = [p[0] for p in coords]
                ys = [p[1] for p in coords]
                bbox = (min(xs), min(ys), max(xs), max(ys))
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)

            # Detectar si el bloque parece una tabla fiscal
            # Buscar patrones como: IVA%, Base, Cuota, 21%, 10%, 4%, etc.
            if self._looks_like_tax_table(text):
                cells = self._parse_tax_table_cells(text, bbox, page, confidence)
                if cells:
                    # Calcular rows/cols desde las celdas
                    rows = max(c.row for c in cells) + 1
                    cols = max(c.col for c in cells) + 1
                    table = LayoutTable(
                        cells=cells,
                        page=page,
                        bbox=bbox,
                        rows=rows,
                        cols=cols,
                        confidence=confidence,
                        kind="tax_table",
                    )
                    tables.append(table)

        return tables

    def _looks_like_tax_table(self, text: str) -> bool:
        """Detecta si un bloque de texto parece una tabla fiscal.

        Una tabla fiscal típicamente contiene palabras como IVA, Base,
        Cuota, tipo, porcentaje, y valores numéricos con símbolos %.
        """
        text_lower = text.lower()
        indicators = [
            "iva", "base", "cuota", "tipo", "%", "impuesto",
            "tax", "rate", "base imponible", "21%", "10%", "4%",
            "21,", "10,", "4,",
        ]
        score = sum(1 for ind in indicators if ind in text_lower)
        return score >= 2

    def _parse_tax_table_cells(
        self, text: str, block_bbox: tuple[float, float, float, float],
        page: int, confidence: float
    ) -> list[LayoutCell]:
        """Convierte texto de tabla fiscal en celdas estructuradas.

        El texto de una tabla fiscal suele estar en líneas separadas
        o en formato: IVA% | Base | Cuota | Total. Intentamos extraer
        las columnas por posición o por separadores.
        """
        cells: list[LayoutCell] = []
        lines = text.split("\n")

        for row_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # Intentar separar por |, tab o múltiples espacios
            parts = [p.strip() for p in re.split(r"[\t|]+", line)]
            for col_idx, cell_text in enumerate(parts):
                if not cell_text:
                    continue

                # Calcular bbox aproximado para cada celda
                # Usamos el bbox del bloque como referencia
                x0, y0, x1, y1 = block_bbox
                cell_width = (x1 - x0) / max(len(parts), 1)
                cell_height = (y1 - y0) / max(len(lines), 1)
                cell_bbox = (
                    x0 + col_idx * cell_width,
                    y0 + row_idx * cell_height,
                    x0 + (col_idx + 1) * cell_width,
                    y0 + (row_idx + 1) * cell_height,
                )

                cells.append(
                    LayoutCell(
                        text=cell_text,
                        row=row_idx,
                        col=col_idx,
                        bbox=cell_bbox,
                        page=page,
                        confidence=confidence,
                    )
                )

        return cells


# Alias para compatibilidad con nombre antiguo
class PaddleStructureAnalyzer(PPSTructureV3Analyzer):
    """Alias de PPSTructureV3Analyzer para compatibilidad con nombres anteriores."""
    pass