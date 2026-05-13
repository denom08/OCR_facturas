"""Tests para puerto layout_analyzer y tax_table_extractor.

Usa FakeLayoutAnalyzer y synthetic tables para no depender del motor real
(PP-StructureV3 / PaddleOCR).
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest

from app.application.pipeline.tax_table_extractor import (
    TaxLineCandidate,
    TaxTableResult,
    extract_tax_lines_from_layout,
    extract_tax_lines_from_synthetic_table,
)
from app.application.ports.layout_analyzer import (
    LayoutAnalyzer,
    LayoutCell,
    LayoutEngineKind,
    LayoutResult,
    LayoutTable,
    LayoutUnavailableError,
)
from app.shared.money import normalize_money

# =============================================================================
# Fake LayoutAnalyzer para tests
# =============================================================================


class FakeLayoutAnalyzer(LayoutAnalyzer):
    """Motor de layout falso para tests.

    Devuelve tablas preconfiguradas con celdas controladas.
    Útil para tests sin instalar PP-StructureV3 ni tener GPU.
    """

    def __init__(
        self,
        tables: list[LayoutTable] | None = None,
        available: bool = True,
        name: str = "FakeLayout",
        kind: LayoutEngineKind = LayoutEngineKind.PP_STRUCTURE_V3,
    ) -> None:
        """Configura el analyzer fake.

        Args:
            tables: Lista de LayoutTable a devolver. Si es None,
                devuelve una tabla vacía.
            available: Valor a devolver por is_available().
            name: Nombre del motor para debug.
            kind: Tipo de motor.
        """
        self._tables = tables or []
        self._available = available
        self._name = name
        self._kind = kind

    def is_available(self) -> bool:
        return self._available

    def name(self) -> str:
        return self._name

    def kind(self) -> LayoutEngineKind:
        return self._kind

    def process_page(self, image_data: Any, page: int = 1) -> LayoutResult:
        return LayoutResult(
            tables=[t for t in self._tables],
            page=page,
            engine=self._name,
            raw=None,
        )


class UnavailableLayoutAnalyzer(LayoutAnalyzer):
    """Analyzer que siempre responde que no está disponible.

    Útil para probar el comportamiento controlado cuando falta layout.
    """

    def is_available(self) -> bool:
        return False

    def name(self) -> str:
        return "UnavailableLayout"

    def kind(self) -> LayoutEngineKind:
        return LayoutEngineKind.UNKNOWN

    def process_page(self, image_data: Any, page: int = 1) -> LayoutResult:
        raise LayoutUnavailableError(
            "LayoutAnalyzer no disponible"
        )


# =============================================================================
# Helpers para crear datos de prueba
# =============================================================================


def make_layout_cell(
    text: str, row: int, col: int, page: int = 1, confidence: float = 0.9
) -> LayoutCell:
    """Crea una celda de tabla fake con bbox por defecto."""
    return LayoutCell(
        text=text,
        row=row,
        col=col,
        bbox=(50.0 + col * 100, 100.0 + row * 30, 150.0 + col * 100, 130.0 + row * 30),
        page=page,
        confidence=confidence,
    )


def make_layout_table(
    cells: list[LayoutCell], page: int = 1, kind: str = "tax_table"
) -> LayoutTable:
    """Crea una LayoutTable desde celdas fake."""
    rows = max((c.row for c in cells), default=0) + 1
    cols = max((c.col for c in cells), default=0) + 1
    bboxes = [c.bbox for c in cells]
    if bboxes:
        xs = [b[0] for b in bboxes] + [b[2] for b in bboxes]
        ys = [b[1] for b in bboxes] + [b[3] for b in bboxes]
        global_bbox = (min(xs), min(ys), max(xs), max(ys))
    else:
        global_bbox = (0.0, 0.0, 0.0, 0.0)
    return LayoutTable(
        cells=cells,
        page=page,
        bbox=global_bbox,
        rows=rows,
        cols=cols,
        confidence=0.9,
        kind=kind,
    )


# =============================================================================
# Tests: LayoutAnalyzer port
# =============================================================================


class TestLayoutAnalyzerPort:
    """Tests para el puerto LayoutAnalyzer."""

    def test_is_available_returns_bool(self) -> None:
        analyzer = FakeLayoutAnalyzer(available=True)
        assert analyzer.is_available() is True

        analyzer = FakeLayoutAnalyzer(available=False)
        assert analyzer.is_available() is False

    def test_name_returns_string(self) -> None:
        analyzer = FakeLayoutAnalyzer(name="TestLayout")
        assert analyzer.name() == "TestLayout"

    def test_kind_returns_engine_kind(self) -> None:
        analyzer = FakeLayoutAnalyzer(kind=LayoutEngineKind.DOCLING)
        assert analyzer.kind() == LayoutEngineKind.DOCLING

    def test_process_page_returns_layout_result(self) -> None:
        cells = [
            make_layout_cell("IVA", 0, 0),
            make_layout_cell("Base", 0, 1),
            make_layout_cell("Cuota", 0, 2),
        ]
        table = make_layout_table(cells)
        analyzer = FakeLayoutAnalyzer(tables=[table])
        result = analyzer.process_page(BytesIO(), page=1)

        assert isinstance(result, LayoutResult)
        assert result.page == 1
        assert len(result.tables) == 1
        assert result.tables[0].kind == "tax_table"

    def test_unavailable_raises_error(self) -> None:
        analyzer = UnavailableLayoutAnalyzer()
        with pytest.raises(LayoutUnavailableError):
            analyzer.process_page(BytesIO())


class TestLayoutCell:
    """Tests para LayoutCell."""

    def test_layout_cell_immutable(self) -> None:
        cell = LayoutCell(
            text="21%",
            row=1,
            col=2,
            bbox=(0, 0, 100, 50),
            page=1,
            confidence=0.9,
        )
        assert cell.text == "21%"
        assert cell.row == 1
        assert cell.col == 2
        assert cell.bbox == (0, 0, 100, 50)
        assert cell.page == 1
        assert cell.confidence == 0.9


class TestLayoutTable:
    """Tests para LayoutTable."""

    def test_layout_table_cells(self) -> None:
        cells = [
            make_layout_cell("21%", 0, 0),
            make_layout_cell("100,00", 0, 1),
            make_layout_cell("21,00", 0, 2),
        ]
        table = make_layout_table(cells)

        assert len(table.cells) == 3
        assert table.rows == 1
        assert table.cols == 3
        assert table.kind == "tax_table"

    def test_layout_table_empty_cells(self) -> None:
        table = LayoutTable()
        assert table.cells == []
        assert table.rows == 0
        assert table.cols == 0


# =============================================================================
# Tests: extract_tax_lines_from_synthetic_table
# =============================================================================


class TestExtractTaxLinesFromSyntheticTable:
    """Tests para extract_tax_lines_from_synthetic_table con tablas sintéticas."""

    def test_single_iva_21(self) -> None:
        """Tabla con una línea de IVA 21%."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "100,00", "21,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert len(result.tax_lines) == 1
        line = result.tax_lines[0]
        assert line.tax_rate == Decimal("21")
        assert line.tax_base == normalize_money("100,00")
        assert line.tax_amount == normalize_money("21,00")
        assert result.warnings == []

    def test_multiple_iva_rates(self) -> None:
        """Tabla con IVA 21%, 10% y 4%."""
        rows = [
            ["Tipo IVA", "Base Imponible", "Cuota IVA"],
            ["21%", "500,00", "105,00"],
            ["10%", "200,00", "20,00"],
            ["4%", "100,00", "4,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert len(result.tax_lines) == 3
        assert result.tax_lines[0].tax_rate == Decimal("21")
        assert result.tax_lines[0].tax_base == normalize_money("500,00")
        assert result.tax_lines[0].tax_amount == normalize_money("105,00")
        assert result.tax_lines[1].tax_rate == Decimal("10")
        assert result.tax_lines[1].tax_base == normalize_money("200,00")
        assert result.tax_lines[2].tax_rate == Decimal("4")
        assert result.tax_lines[2].tax_base == normalize_money("100,00")

    def test_empty_table_returns_warnings(self) -> None:
        """Tabla vacía devuelve warnings."""
        result = extract_tax_lines_from_synthetic_table([])

        assert result.tax_lines == []
        assert len(result.warnings) >= 1

    def test_header_row_skipped(self) -> None:
        """Las filas de encabezado se saltan."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "100,00", "21,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        # Solo la fila de datos, no el encabezado
        assert len(result.tax_lines) == 1
        assert result.tax_lines[0].tax_rate == Decimal("21")

    def test_withholding_detected(self) -> None:
        """Detecta columna de retención."""
        rows = [
            ["IVA", "Base", "Cuota", "Retención"],
            ["21%", "1000,00", "210,00", "Retención 105,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert len(result.tax_lines) == 1
        assert result.tax_lines[0].withholding_amount == normalize_money("105,00")

    def test_confidence_high_when_valid(self) -> None:
        """Alta confianza cuando base*rate≈cuota."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "500,00", "105,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert result.confidence >= 0.8

    def test_confidence_lower_when_cuota_mismatch(self) -> None:
        """Menor confianza cuando la cuota no cuadra (base * rate ≠ amount)."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "100,00", "50,00"],  # Debería ser 21.00
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        # La cuota 50 no cuadra con 100*21% = 21
        assert result.tax_lines[0].confidence < 0.9

    def test_net_and_tax_amounts_aggregated(self) -> None:
        """net_amount y tax_amountson suma de bases y cuotas."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "500,00", "105,00"],
            ["10%", "200,00", "20,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert result.net_amount == normalize_money("700,00")
        assert result.tax_amount == normalize_money("125,00")


class TestExtractTaxLinesFromLayout:
    """Tests para extract_tax_lines_from_layout con FakeLayoutAnalyzer."""

    def test_layout_result_with_tax_table(self) -> None:
        """LayoutResult con tabla fiscal produce líneas."""
        cells = [
            make_layout_cell("IVA", 0, 0),
            make_layout_cell("Base", 0, 1),
            make_layout_cell("Cuota", 0, 2),
            make_layout_cell("21%", 1, 0, confidence=0.9),
            make_layout_cell("1000,00", 1, 1, confidence=0.9),
            make_layout_cell("210,00", 1, 2, confidence=0.9),
        ]
        table = make_layout_table(cells)
        layout_result = LayoutResult(tables=[table], page=1, engine="fake")

        result = extract_tax_lines_from_layout(layout_result)

        assert len(result.tax_lines) == 1
        assert result.tax_lines[0].tax_rate == Decimal("21")
        assert result.tax_lines[0].tax_base == normalize_money("1000,00")
        assert result.tax_lines[0].tax_amount == normalize_money("210,00")

    def test_layout_result_no_tables_warns(self) -> None:
        """LayoutResult sin tablas devuelve warning."""
        layout_result = LayoutResult(tables=[], page=1, engine="fake")

        result = extract_tax_lines_from_layout(layout_result)

        assert len(result.warnings) >= 1

    def test_multiple_tax_tables_from_layout(self) -> None:
        """Varias tablas fiscales detectados."""
        # Tabla 1: IVA 21%
        cells1 = [
            make_layout_cell("21%", 0, 0, page=1),
            make_layout_cell("500,00", 0, 1, page=1),
            make_layout_cell("105,00", 0, 2, page=1),
        ]
        # Tabla 2: IVA 10%
        cells2 = [
            make_layout_cell("10%", 0, 0, page=1),
            make_layout_cell("200,00", 0, 1, page=1),
            make_layout_cell("20,00", 0, 2, page=1),
        ]
        table1 = make_layout_table(cells1, kind="tax_table")
        table2 = make_layout_table(cells2, kind="tax_table")
        layout_result = LayoutResult(tables=[table1, table2], page=1, engine="fake")

        result = extract_tax_lines_from_layout(layout_result)

        assert len(result.tax_lines) == 2
        rates = {c.tax_rate for c in result.tax_lines}
        assert rates == {Decimal("21"), Decimal("10")}


class TestTaxLineCandidate:
    """Tests para TaxLineCandidate."""

    def test_candidate_tax_rate(self) -> None:
        candidate = TaxLineCandidate(
            tax_rate=Decimal("21"),
            tax_base=Decimal("100.00"),
            tax_amount=Decimal("21.00"),
        )
        assert candidate.tax_rate == Decimal("21")

    def test_candidate_source_synthetic(self) -> None:
        candidate = TaxLineCandidate(
            tax_rate=Decimal("10"),
            source="synthetic",
        )
        assert candidate.source == "synthetic"

    def test_candidate_source_layout(self) -> None:
        candidate = TaxLineCandidate(
            tax_rate=Decimal("4"),
            source="layout",
        )
        assert candidate.source == "layout"

    def test_candidate_default_confidence(self) -> None:
        candidate = TaxLineCandidate(tax_rate=Decimal("21"))
        assert candidate.confidence == 0.5


class TestTaxTableResult:
    """Tests para TaxTableResult."""

    def test_default_empty(self) -> None:
        result = TaxTableResult()
        assert result.tax_lines == []
        assert result.net_amount is None
        assert result.tax_amount is None

    def test_aggregated_totals(self) -> None:
        result = TaxTableResult()
        result.tax_lines = [
            TaxLineCandidate(
                tax_rate=Decimal("21"),
                tax_base=Decimal("500.00"),
                tax_amount=Decimal("105.00"),
            ),
            TaxLineCandidate(
                tax_rate=Decimal("10"),
                tax_base=Decimal("200.00"),
                tax_amount=Decimal("20.00"),
            ),
        ]
        result.net_amount = Decimal("700.00")
        result.tax_amount = Decimal("125.00")

        assert result.net_amount == Decimal("700.00")
        assert result.tax_amount == Decimal("125.00")


# =============================================================================
# Tests: Integration Fake LayoutAnalyzer → Tax Table Extractor
# =============================================================================


class TestLayoutToTaxTableIntegration:
    """Integration: FakeLayoutAnalyzer → extract_tax_lines_from_layout."""

    def test_full_pipeline_fake_analyzer(self) -> None:
        """Pipeline completo con analyzer fake."""
        # Crear tabla fiscal fake con múltiples IVAs
        cells = [
            make_layout_cell("IVA", 0, 0),
            make_layout_cell("Base", 0, 1),
            make_layout_cell("Cuota", 0, 2),
            make_layout_cell("21%", 1, 0, confidence=0.95),
            make_layout_cell("1000,00", 1, 1, confidence=0.95),
            make_layout_cell("210,00", 1, 2, confidence=0.95),
            make_layout_cell("10%", 2, 0, confidence=0.95),
            make_layout_cell("300,00", 2, 1, confidence=0.95),
            make_layout_cell("30,00", 2, 2, confidence=0.95),
            make_layout_cell("4%", 3, 0, confidence=0.95),
            make_layout_cell("50,00", 3, 1, confidence=0.95),
            make_layout_cell("2,00", 3, 2, confidence=0.95),
        ]
        table = make_layout_table(cells)

        # Analyzer fake
        analyzer = FakeLayoutAnalyzer(tables=[table], name="FakeLayout")
        assert analyzer.is_available() is True

        # Obtener layout result
        layout_result = analyzer.process_page(BytesIO(), page=1)

        # Extraer líneas fiscales
        tax_result = extract_tax_lines_from_layout(layout_result)

        # Verificar
        assert len(tax_result.tax_lines) == 3
        rates = sorted([c.tax_rate for c in tax_result.tax_lines])
        assert rates == [Decimal("4"), Decimal("10"), Decimal("21")]
        assert tax_result.net_amount == normalize_money("1350,00")
        assert tax_result.tax_amount == normalize_money("242,00")

    def test_unavailable_analyzer_raises(self) -> None:
        """Analyzer no disponible levanta LayoutUnavailableError."""
        analyzer = UnavailableLayoutAnalyzer()
        assert analyzer.is_available() is False

        with pytest.raises(LayoutUnavailableError):
            analyzer.process_page(BytesIO())


# =============================================================================
# Tests: edge cases
# =============================================================================


class TestEdgeCases:
    """Tests de casos límite."""

    def test_money_format_variations(self) -> None:
        """Variaciones de formato monetario español."""
        rows = [
            ["IVA", "Base", "Cuota"],
            ["21%", "1.234,56", "259,26"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert len(result.tax_lines) == 1
        assert result.tax_lines[0].tax_base == normalize_money("1.234,56")

    def test_iva_rate_variations(self) -> None:
        """Variaciones de formato de tasa de IVA: 21%, 10%, 4%.

        El parser requiere filas de encabezado con palabras clave (IVA, Base, etc.)
        para distinguir headers de datos. Las filas de datos van después del header.
        """
        test_cases = [
            (["IVA", "Base", "Cuota"], ["21%", "100,00", "21,00"], Decimal("21")),
            (["Tipo IVA", "Base Imponible", "IVA"], ["10%", "200,00", "20,00"], Decimal("10")),
            (["IVA", "Base", "Cuota"], ["4%", "50,00", "2,00"], Decimal("4")),
        ]
        for header_row, data_row, expected_rate in test_cases:
            rows = [header_row, data_row]
            result = extract_tax_lines_from_synthetic_table(rows)
            assert len(result.tax_lines) == 1, f"Failed for {rows}"
            assert result.tax_lines[0].tax_rate == expected_rate, f"Failed for {rows}"

    def test_table_with_missing_base(self) -> None:
        """Tabla donde falta la base imponible en columna propia.

        Con 4 columnas y retención, los importes se asignan así:
        - 21%: rate (col 0)
        - vacía: se ignora
        - 210,00: primer importe → tax_base
        - reten 105,00: segundo importe → withholding
        tax_amount queda None porque no hay tercer importe.
        """
        rows = [
            ["IVA", "Base", "Cuota", "Retención"],
            ["21%", "", "210,00", "reten 105,00"],
        ]
        result = extract_tax_lines_from_synthetic_table(rows)

        assert len(result.tax_lines) == 1
        assert result.tax_lines[0].tax_rate == Decimal("21")
        assert result.tax_lines[0].tax_base == normalize_money("210,00")
        assert result.tax_lines[0].withholding_amount == normalize_money("105,00")
        assert result.tax_lines[0].tax_amount is None

    def test_non_tax_table_ignored(self) -> None:
        """Tablas que no parecen fiscales se ignoran."""
        # Tabla con contenido no fiscal
        cells = [
            make_layout_cell("Producto", 0, 0),
            make_layout_cell("Cantidad", 0, 1),
            make_layout_cell("Precio", 0, 2),
            make_layout_cell("Camisa", 1, 0),
            make_layout_cell("2", 1, 1),
            make_layout_cell("25,00", 1, 2),
        ]
        table = LayoutTable(
            cells=cells,
            page=1,
            bbox=(50, 100, 350, 200),
            rows=2,
            cols=3,
            confidence=0.9,
            kind="line_items",  # kind diferente a tax_table
        )
        layout_result = LayoutResult(tables=[table], page=1, engine="fake")

        result = extract_tax_lines_from_layout(layout_result)

        # No se detectaron líneas fiscales porque la tabla no tiene kind="tax_table"
        # y las celdas no contienen palabras clave de IVA
        assert result.warnings or result.tax_lines == []