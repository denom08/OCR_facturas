"""Extractor de tablas fiscales desde LayoutResult.

Consume LayoutResult (tablas detectadas por PP-StructureV3 u otro motor)
y produce candidatos de líneas de IVA: base, tipo de IVA, cuota y total.

El diseño es SYnthetic-first: funciona con tablas sintéticas generadas
desde NormalizedDocument cuando no hay motor de layout real disponible.
Esto permite tests reproducibles sin GPU ni modelos pesados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.application.ports.layout_analyzer import (
    LayoutCell,
    LayoutResult,
)
from app.shared.money import normalize_money

# -------------------------------------------------------------------
# Tasas de IVA válidas en España
# -------------------------------------------------------------------

VALID_IVA_RATES = {21.0, 10.0, 4.0, 0.0}
IVA_RATE_KEYWORDS = {
    21.0: ["21%", "iva 21", "tipo 21", "21,00%"],
    10.0: ["10%", "iva 10", "tipo 10", "10,00%"],
    4.0: ["4%", "iva 4", "tipo 4", "4,00%"],
    0.0: ["0%", "iva 0", "exento", "exenta"],
}

# -------------------------------------------------------------------
# Candidato de línea fiscal
# -------------------------------------------------------------------


@dataclass(frozen=True)
class TaxLineCandidate:
    """Un candidato de línea fiscal extraído desde una tabla.

    Representa: tipo de IVA, base imponible, cuota de IVA y opcionalmente
    retención o total. Se genera desde LayoutTable y se combina con
    TaxLineAmounts de totals_validator para validación.
    """

    tax_rate: Decimal  # porcentaje: 21.0, 10.0, 4.0
    tax_base: Decimal | None = None  # base imponible en euros
    tax_amount: Decimal | None = None  # cuota de IVA en euros
    withholding_amount: Decimal | None = None  # retención si aparece
    confidence: float = 0.5  # 0.0-1.0
    page: int = 1
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    source: Literal["layout", "synthetic"] = "synthetic"


# -------------------------------------------------------------------
# Resultado del extractor de tablas fiscales
# -------------------------------------------------------------------


@dataclass
class TaxTableResult:
    """Resultado completo del extractor de tablas fiscales.

    Contiene líneas fiscales detectadas (candidatos), totales agregados
    y advertencias sobre datos faltantes o ambiguos.
    """

    tax_lines: list[TaxLineCandidate] = field(default_factory=list)
    net_amount: Decimal | None = None  # suma de bases
    tax_amount: Decimal | None = None  # suma de cuotas
    gross_amount: Decimal | None = None  # total factura
    advance_amount: Decimal | None = None
    withholding_amount: Decimal | None = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)


# -------------------------------------------------------------------
# Funciones de extracción
# -------------------------------------------------------------------


def extract_tax_lines_from_layout(layout_result: LayoutResult) -> TaxTableResult:
    """Procesa un LayoutResult y extrae líneas fiscales desde tablas detectadas.

    Args:
        layout_result: Resultado del análisis de layout con tablas.

    Returns:
        TaxTableResult con candidatos de líneas fiscales, totales y warnings.
    """
    result = TaxTableResult()
    all_cells: list[LayoutCell] = []

    # Recoger todas las celdas de tablas detectadas
    # Añadimos row_offset por tabla para evitar colisiones de índices
    row_offset = 0
    for table in layout_result.tables:
        if table.kind in ("tax_table", "unknown"):
            for cell in table.cells:
                # Crear celda con row absoluto para evitar mezcla entre tablas
                all_cells.append(
                    LayoutCell(
                        text=cell.text,
                        row=cell.row + row_offset,
                        col=cell.col,
                        bbox=cell.bbox,
                        page=cell.page,
                        confidence=cell.confidence,
                    )
                )
            row_offset += table.rows + 1  # offset para la siguiente tabla

    if not all_cells:
        result.warnings.append("No se detectaron tablas fiscales en el layout.")
        return result

    # Parsear las celdas para extraer líneas de IVA
    tax_line_candidates = _parse_tax_cells(all_cells)

    if not tax_line_candidates:
        result.warnings.append(
            "Se detectaron tablas pero no se pudo extraer líneas fiscales. "
            "Verificar que las tablas contengan columnas de IVA/base/cuota."
        )
        return result

    result.tax_lines = tax_line_candidates
    result.confidence = _compute_confidence(tax_line_candidates)

    # Calcular totales agregados
    result.net_amount = _sum_bases(tax_line_candidates)
    result.tax_amount = _sum_amounts(tax_line_candidates)

    return result


def extract_tax_lines_from_synthetic_table(
    rows: list[list[str]],
    *,
    page: int = 1,
) -> TaxTableResult:
    """Extrae líneas fiscales desde una tabla sintética (sin motor de layout real).

    Args:
        rows: Lista de filas, cada fila es una lista de celdas de texto.
              Ejemplo: [["IVA", "Base", "Cuota"], ["21%", "100,00", "21,00"], ...]
        page: Número de página para evidencias.

    Returns:
        TaxTableResult con candidatos de líneas fiscales.
    """
    result = TaxTableResult()

    if not rows:
        result.warnings.append("Tabla sintética vacía.")
        return result

    # Convertir filas en LayoutCell falsas para reutilizar el parser
    fake_cells: list[LayoutCell] = []
    for row_idx, row in enumerate(rows):
        for col_idx, cell_text in enumerate(row):
            if cell_text.strip():
                fake_cells.append(
                    LayoutCell(
                        text=cell_text.strip(),
                        row=row_idx,
                        col=col_idx,
                        bbox=(0.0, 0.0, 0.0, 0.0),
                        page=page,
                        confidence=0.8,
                    )
                )

    if not fake_cells:
        result.warnings.append("Tabla sintética sin celdas con texto.")
        return result

    # Parsear las celdas falsas
    tax_line_candidates = _parse_tax_cells(fake_cells)

    if not tax_line_candidates:
        result.warnings.append(
            "No se pudieron extraer líneas fiscales desde la tabla sintética. "
            "Verificar que las columnas contengan tasas de IVA válidas (21%, 10%, 4%) "
            "y valores monetarios en formato español (1.234,56)."
        )
        return result

    result.tax_lines = tax_line_candidates
    result.confidence = _compute_confidence(tax_line_candidates)
    result.net_amount = _sum_bases(tax_line_candidates)
    result.tax_amount = _sum_amounts(tax_line_candidates)

    return result


def _parse_tax_cells(cells: list[LayoutCell]) -> list[TaxLineCandidate]:
    """Convierte celdas de tabla en candidatos de líneas fiscales.

    Detecta columnas por posición y contenido:
    - Columna de tipo IVA: valores 21%, 10%, 4%, etc.
    - Columna de base: importes en formato español (1.234,56)
    - Columna de cuota: importes en formato español
    - Columna de retención: importes con etiqueta de retención
    """
    candidates: list[TaxLineCandidate] = []

    # Agrupar celdas por fila
    rows_by_index: dict[int, list[LayoutCell]] = {}
    for cell in cells:
        if cell.row not in rows_by_index:
            rows_by_index[cell.row] = []
        rows_by_index[cell.row].append(cell)

    # Ordenar filas y columnas
    for row_idx in sorted(rows_by_index.keys()):
        row_cells = sorted(rows_by_index[row_idx], key=lambda c: c.col)
        row_texts = [c.text for c in row_cells]

        # Detectar si la fila es una fila de encabezado (contiene palabras clave)
        if _is_header_row(row_texts):
            continue  # Saltar encabezado

        # Extraer candidato de esta fila
        candidate = _extract_candidate_from_row(row_cells, row_texts)
        if candidate:
            candidates.append(candidate)

    return candidates


def _is_header_row(row_texts: list[str]) -> bool:
    """Detecta si una fila es de encabezado (contiene palabras clave de IVA)."""
    text_combined = " ".join(row_texts).lower()
    header_keywords = [
        "iva", "tipo", "base", "cuota", "total", "impuesto",
        "tax", "rate", "porcentaje", "%", "base imponible",
    ]
    score = sum(1 for kw in header_keywords if kw in text_combined)
    return score >= 2


def _extract_candidate_from_row(
    row_cells: list[LayoutCell], row_texts: list[str]
) -> TaxLineCandidate | None:
    """Extrae un TaxLineCandidate desde una fila de celdas."""
    # Primero, identificar la celda que contiene el tipo de IVA (rate)
    tax_rate: Decimal | None = None
    rate_col_idx: int | None = None

    for col_idx, cell_text in enumerate(row_texts):
        rate = _parse_iva_rate(cell_text)
        if rate is not None:
            tax_rate = rate
            rate_col_idx = col_idx
            break

    if tax_rate is None:
        return None

    # Ahora recorrer las celdas para extraer base, amount y withholding
    # Saltando la celda del tipo de IVA identificada
    tax_base: Decimal | None = None
    tax_amount: Decimal | None = None
    withholding: Decimal | None = None

    for col_idx, cell_text in enumerate(row_texts):
        if col_idx == rate_col_idx:
            continue  # Saltar la celda del tipo de IVA

        # Detectar retención por etiqueta en la celda
        if "reten" in cell_text.lower() and col_idx > 0:
            # Extraer el importe numérico que sigue a la palabra retención
            amount = _parse_money_from_retencion(cell_text)
            if amount is not None:
                withholding = amount
            continue

        # Detectar importes (no parsear si es el tipo de IVA)
        amount = _parse_money(cell_text)
        if amount is not None:
            if tax_base is None:
                tax_base = amount
            elif tax_amount is None:
                tax_amount = amount

    confidence = _compute_row_confidence(tax_rate, tax_base, tax_amount, row_cells)
    bbox = _merge_bboxes([c.bbox for c in row_cells])
    page = row_cells[0].page if row_cells else 1

    return TaxLineCandidate(
        tax_rate=tax_rate,
        tax_base=tax_base,
        tax_amount=tax_amount,
        withholding_amount=withholding,
        confidence=confidence,
        page=page,
        bbox=bbox,
        source="synthetic" if all(c.confidence < 1.0 for c in row_cells) else "layout",
    )


def _parse_iva_rate(text: str) -> Decimal | None:
    """Detecta si un texto contiene una tasa de IVA válida (21%, 10%, 4%).

    Solo reconoce formatos de porcentaje explícito: 21%, 10%, 4%.
    NO acepta "21" solo como rate (se confundiría con importes).
    """
    text_clean = text.strip().lower()

    # Solo aceptar si HAY símbolo de %
    pct_match = re.search(r"(\d+)[.,]?\d*\s*%", text_clean)
    if pct_match:
        rate = Decimal(pct_match.group(1))
        if rate in VALID_IVA_RATES:
            return rate

    return None


def _parse_money(text: str) -> Decimal | None:
    """Convierte texto de importe en Decimal si es válido."""
    try:
        # Limpiar símbolo de euro y espacios
        text_clean = text.strip().replace("€", "").replace("EUR", "").strip()
        return normalize_money(text_clean)
    except (ValueError, Exception):
        return None


def _parse_money_from_retencion(text: str) -> Decimal | None:
    """Extrae el importe numérico de una celda de retención.

    La celda puede tener formato "Retención 105,00" o "Retención105,00" o
    "reten 105,00". Necesitamos encontrar el número dentro del texto.
    """
    # Buscar el primer número con formato español
    # Pattern: encuentra importes tipo "105,00" o "1.234,56"
    match = re.search(r"([0-9]{1,3}(?:[.,]\d{3})*[.,]\d{2})", text)
    if match:
        return _parse_money(match.group(1))

    # Fallback: buscar cualquier número decimal
    match = re.search(r"(\d+[.,]\d+)", text)
    if match:
        return _parse_money(match.group(1))

    return None


def _compute_row_confidence(
    rate: Decimal | None,
    base: Decimal | None,
    amount: Decimal | None,
    cells: list[LayoutCell],
) -> float:
    """Calcula confianza de una fila de tabla fiscal."""
    if rate is None:
        return 0.0

    base_conf = cells[0].confidence if cells else 0.5
    rate_conf = 0.8 if rate in VALID_IVA_RATES else 0.4

    # Alta confianza si tenemos base y cuota
    if base is not None and amount is not None:
        # Verificar que base * rate / 100 ≈ amount
        expected_amount = base * rate / Decimal("100")
        diff = abs(expected_amount - amount)
        if diff <= Decimal("0.50"):
            return min(0.95, (base_conf + rate_conf + 0.9) / 3)
        else:
            # La cuota no cuadra con la base*rate, menor confianza
            return min(0.7, (base_conf + rate_conf + 0.6) / 3)

    return (base_conf + rate_conf) / 2


def _compute_confidence(candidates: list[TaxLineCandidate]) -> float:
    """Calcula confianza agregada de todas las líneas fiscales."""
    if not candidates:
        return 0.0
    return sum(c.confidence for c in candidates) / len(candidates)


def _sum_bases(candidates: list[TaxLineCandidate]) -> Decimal:
    """Suma de bases imponibles."""
    return sum((c.tax_base or Decimal("0")) for c in candidates)


def _sum_amounts(candidates: list[TaxLineCandidate]) -> Decimal:
    """Suma de cuotas de IVA."""
    return sum((c.tax_amount or Decimal("0")) for c in candidates)


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    """Fusiona múltiples bboxes en uno global."""
    if not bboxes:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [b[0] for b in bboxes] + [b[2] for b in bboxes]
    ys = [b[1] for b in bboxes] + [b[3] for b in bboxes]
    return (min(xs), min(ys), max(xs), max(ys))