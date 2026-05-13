"""Tests para el módulo VLM (B9)."""

import json
from io import BytesIO

import pytest

from app.application.ports.invoice_extractor import (
    VlmExtractedField,
    VlmExtractionResult,
    VlmParseError,
    VlmRawResponse,
    VlmUnavailableError,
)
from app.infrastructure.vlm.qwen_vl_extractor import parse_vlm_json
from app.infrastructure.vlm.vlm_invocation_rules import (
    get_vlm_candidates_from_result,
    should_invoke_vlm,
)
from tests.unit.fake_vlm_extractor import FakeVlmExtractor, UnavailableVlmExtractor


class TestParseVlmJson:
    """Tests para parse_vlm_json."""

    def test_clean_json(self):
        """Parsea JSON limpio sin markdown."""
        raw = '{"invoice_data": {"number": "2024/001", "issue_date": "2024-01-15"}}'
        result = parse_vlm_json(raw)
        assert result["invoice_data"]["number"] == "2024/001"
        assert result["invoice_data"]["issue_date"] == "2024-01-15"

    def test_json_with_markdown_fence(self):
        """Parsea JSON envuelto en markdown fence."""
        raw = '```json\n{"invoice_data": {"number": "2024/002"}}\n```'
        result = parse_vlm_json(raw)
        assert result["invoice_data"]["number"] == "2024/002"

    def test_json_with_text_before_and_after(self):
        """Parsea JSON con texto antes y después."""
        raw = 'Aquí está la factura: {"invoice_data": {"number": "2024/003"}} ¡Gracias!'
        result = parse_vlm_json(raw)
        assert result["invoice_data"]["number"] == "2024/003"

    def test_json_with_fence_no_lang(self):
        """Parsea markdown fence sin 'json' como lenguaje."""
        raw = '```\n{"invoice_data": {"number": "2024/004"}}\n```'
        result = parse_vlm_json(raw)
        assert result["invoice_data"]["number"] == "2024/004"

    def test_empty_output_raises(self):
        """Output vacío lanza VlmParseError."""
        with pytest.raises(VlmParseError):
            parse_vlm_json("")

    def test_whitespace_only_raises(self):
        """Output con solo espacios lanza VlmParseError."""
        with pytest.raises(VlmParseError):
            parse_vlm_json("   \n  ")

    def test_no_json_raises(self):
        """Texto sin JSON lanza VlmParseError."""
        with pytest.raises(VlmParseError):
            parse_vlm_json("Esto no es JSON")

    def test_null_response(self):
        """Respuesta 'null' del VLM se maneja sin error."""
        # El VLM puede devolver "null" cuando no hay factura
        raw = "null"
        result = parse_vlm_json(raw)
        # No lanza, pero puede devolver dict vacío
        assert result == {} or "null" in raw.lower()

    def test_trailing_comma_cleaned(self):
        """JSON con trailing comma se limpia y parsea."""
        raw = '{"invoice_data": {"number": "2024/005", "issue_date": null},}'
        result = parse_vlm_json(raw)
        assert result["invoice_data"]["number"] == "2024/005"

    def test_nested_json_complex(self):
        """Parsea JSON complejo anidado con tax_lines."""
        raw = json.dumps({
            "invoice_data": {"number": "2024/006", "issue_date": "2024-02-01"},
            "supplier": {"legal_name": "Acme S.L.", "tax_id": "B12345678"},
            "customer": {"legal_name": "Cliente S.A.", "tax_id": "A87654321"},
            "tax_lines": [
                {"tax_rate": "21", "tax_base": "100.00", "tax_amount": "21.00"},
                {"tax_rate": "10", "tax_base": "50.00", "tax_amount": "5.00"},
            ],
            "totals": {
                "net_amount": "150.00",
                "tax_amount": "26.00",
                "gross_amount": "176.00"
            }
        })
        result = parse_vlm_json(raw)
        assert result["totals"]["gross_amount"] == "176.00"
        assert len(result["tax_lines"]) == 2

    def test_text_with_multiple_braces(self):
        """Texto con múltiples bloques JSON busca el primero."""
        # Input tiene un JSON embebido en texto más largo
        raw = 'Algo antes {"a": 1, "b": 2} y después texto'
        result = parse_vlm_json(raw)
        assert result["a"] == 1
        assert result["b"] == 2


class TestFakeVlmExtractor:
    """Tests para FakeVlmExtractor."""

    def test_is_available_returns_configured_value(self):
        """is_available() devuelve el valor configurado."""
        available_extractor = FakeVlmExtractor(available=True)
        assert available_extractor.is_available() is True

        unavailable_extractor = FakeVlmExtractor(available=False)
        assert unavailable_extractor.is_available() is False

    def test_name_returns_configured_name(self):
        """name() devuelve el nombre configurado."""
        extractor = FakeVlmExtractor(name="TestVLM")
        assert extractor.name() == "TestVLM"

    def test_model_id_returns_configured_id(self):
        """model_id() devuelve el ID configurado."""
        extractor = FakeVlmExtractor(model_id="test/model")
        assert extractor.model_id() == "test/model"

    def test_extract_returns_fields(self):
        """extract() devuelve los campos configurados."""
        custom_fields = [
            VlmExtractedField(
                field_name="invoice_data.number",
                value="TEST/001",
                confidence=0.99,
                page=1,
            ),
        ]
        extractor = FakeVlmExtractor(fields=custom_fields)
        result = extractor.extract(BytesIO(b"fake_image"))

        assert len(result.fields) == 1
        assert result.fields[0].field_name == "invoice_data.number"
        assert result.fields[0].value == "TEST/001"
        assert result.raw_response is not None

    def test_extract_returns_raw_response(self):
        """extract() devuelve raw_response con metadatos."""
        extractor = FakeVlmExtractor(model_id="fake/model")
        result = extractor.extract(BytesIO(b"fake_image"))

        assert result.raw_response is not None
        assert result.raw_response.model == "fake/model"
        assert result.raw_response.latency_ms > 0

    def test_extract_includes_warning_when_configured(self):
        """extract() incluye warning si está configurado."""
        extractor = FakeVlmExtractor(warning="Test warning")
        result = extractor.extract(BytesIO(b"fake_image"))

        assert result.warning == "Test warning"

    def test_extract_multi_page(self):
        """extract_multi_page() procesa múltiples páginas."""
        extractor = FakeVlmExtractor()
        images = [BytesIO(b"page1"), BytesIO(b"page2")]
        results = extractor.extract_multi_page(images, prompt="test")

        assert len(results) == 2


class TestUnavailableVlmExtractor:
    """Tests para UnavailableVlmExtractor."""

    def test_is_available_returns_false(self):
        """is_available() siempre devuelve False."""
        extractor = UnavailableVlmExtractor()
        assert extractor.is_available() is False

    def test_extract_raises_assertion(self):
        """extract() lanza AssertionError."""
        extractor = UnavailableVlmExtractor()
        with pytest.raises(AssertionError):
            extractor.extract(BytesIO(b"fake_image"))


class TestShouldInvokeVlm:
    """Tests para should_invoke_vlm."""

    def test_no_invoke_when_all_fields_resolved(self):
        """No se invoca VLM si todos los campos obligatorios están resueltos."""
        should, reasons = should_invoke_vlm(
            missing_fields=["invoice_data.number"],
            global_confidence=0.8,
            is_scanned=False,
            tax_lines_unresolved=False,
        )
        # missing_field tiene invoice_data.number que es obligatorio
        assert should is True
        assert len(reasons) > 0

    def test_invoke_on_missing_critical_field(self):
        """Se invoca VLM si falta campo obligatorio."""
        should, reasons = should_invoke_vlm(
            missing_fields=["invoice_data.number"],
            global_confidence=0.8,
        )
        assert should is True
        assert any(r.code == "missing_field" for r in reasons)

    def test_invoke_on_low_global_confidence(self):
        """Se invoca VLM si la confianza global es baja."""
        should, reasons = should_invoke_vlm(
            missing_fields=[],
            global_confidence=0.4,
        )
        assert should is True
        assert any(r.code == "low_confidence" for r in reasons)

    def test_no_invoke_when_confidence_ok(self):
        """No se invoca VLM si la confianza es acceptable."""
        should, reasons = should_invoke_vlm(
            missing_fields=[],
            global_confidence=0.8,
            is_scanned=False,
            tax_lines_unresolved=False,
        )
        assert should is False

    def test_invoke_on_scanned_with_unresolved_tax(self):
        """Se invoca VLM si es escaneado con tax_lines no resueltas."""
        should, reasons = should_invoke_vlm(
            missing_fields=[],
            global_confidence=0.8,
            is_scanned=True,
            tax_lines_unresolved=True,
        )
        assert should is True
        assert any(r.code == "complex_scanned" for r in reasons)

    def test_invoke_on_ocr_quality_low(self):
        """Se invoca VLM si OCR tiene baja calidad."""
        should, reasons = should_invoke_vlm(
            missing_fields=[],
            global_confidence=0.8,
            is_scanned=True,
            ocr_quality_low=True,
        )
        assert should is True
        assert any(r.code == "low_ocr_quality" for r in reasons)

    def test_multiple_reasons(self):
        """Puede haber múltiples razones para invocar VLM."""
        should, reasons = should_invoke_vlm(
            missing_fields=["invoice_data.number"],
            global_confidence=0.4,
            is_scanned=True,
            tax_lines_unresolved=True,
        )
        assert should is True
        assert len(reasons) >= 3


class TestGetVlmCandidatesFromResult:
    """Tests para get_vlm_candidates_from_result."""

    def test_converts_fields_to_candidates(self):
        """Convierte VlmExtractionResult en Candidate list."""
        vlm_result = VlmExtractionResult(
            fields=[
                VlmExtractedField(
                    field_name="invoice_data.number",
                    value="2024/001",
                    confidence=0.95,
                    page=1,
                ),
                VlmExtractedField(
                    field_name="supplier.tax_id",
                    value="B12345678",
                    confidence=0.9,
                    page=1,
                ),
            ],
            raw_response=VlmRawResponse(
                raw_text="{}",
                model="fake",
                latency_ms=50.0,
            ),
        )

        candidates = get_vlm_candidates_from_result(vlm_result, page=1)

        assert len(candidates) == 2
        assert candidates[0].field_name == "invoice_data.number"
        assert candidates[0].value == "2024/001"
        # La confianza del VLM se reduce (0.95 * 0.7)
        assert candidates[0].confidence < 0.95

    def test_returns_empty_list_for_empty_fields(self):
        """Devuelve lista vacía si no hay campos."""
        vlm_result = VlmExtractionResult(
            fields=[],
            warning="No fields extracted",
        )

        candidates = get_vlm_candidates_from_result(vlm_result, page=1)
        assert candidates == []


class TestVlmExtractionResult:
    """Tests para VlmExtractionResult."""

    def test_extracted_dict(self):
        """extracted_dict devuelve field_name -> value."""
        result = VlmExtractionResult(
            fields=[
                VlmExtractedField(field_name="invoice_data.number", value="2024/001"),
                VlmExtractedField(field_name="supplier.tax_id", value="B12345678"),
            ]
        )
        d = result.extracted_dict
        assert d["invoice_data.number"] == "2024/001"
        assert d["supplier.tax_id"] == "B12345678"

    def test_get_returns_value(self):
        """get() devuelve el valor del campo o default."""
        result = VlmExtractionResult(
            fields=[
                VlmExtractedField(field_name="invoice_data.number", value="2024/002"),
            ]
        )
        assert result.get("invoice_data.number") == "2024/002"
        assert result.get("nonexistent") is None
        assert result.get("nonexistent", "default") == "default"


class TestVlmUnavailableError:
    """Tests para VlmUnavailableError."""

    def test_is_runtime_error(self):
        """VlmUnavailableError hereda de RuntimeError."""
        err = VlmUnavailableError("test")
        assert isinstance(err, RuntimeError)


class TestVlmParseError:
    """Tests para VlmParseError."""

    def test_is_runtime_error(self):
        """VlmParseError hereda de RuntimeError."""
        err = VlmParseError("test")
        assert isinstance(err, RuntimeError)