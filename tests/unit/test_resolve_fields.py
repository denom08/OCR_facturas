"""Tests para el módulo de resolución de campos y confianza."""

import pytest

from app.application.pipeline.extract_candidates import (
    Candidate,
    CandidateSet,
)
from app.application.pipeline.normalize_document import (
    ExtractionSource,
    NormalizedBlock,
)
from app.application.pipeline.resolve_fields import (
    ResolutionResult,
    ResolvedField,
    SourcePriority,
    adjust_confidence_for_tax_id,
    build_all_evidences,
    build_evidence,
    confidence_per_field,
    global_confidence,
    needs_review,
    resolve_all_fields,
    resolve_document,
    resolve_field,
    source_priority,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_block(
    page: int = 1,
    source: ExtractionSource = ExtractionSource.DIGITAL_TEXT,
) -> NormalizedBlock:
    return NormalizedBlock(
        text="test", bbox=(0, 0, 100, 50), page=page, source=source
    )


def _candidate(
    field_name: str,
    value: str,
    confidence: float,
    source: ExtractionSource = ExtractionSource.DIGITAL_TEXT,
    normalized_value: str | None = None,
) -> Candidate:
    return Candidate(
        field_name=field_name,
        value=value,
        normalized_value=normalized_value,
        confidence=confidence,
        block=_make_block(source=source),
        page=1,
    )


# ---------------------------------------------------------------------------
# Tests: source_priority
# ---------------------------------------------------------------------------


class TestSourcePriority:
    def test_xml_lowest_number(self):
        assert SourcePriority.XML.value == 1

    def test_digital_text_second(self):
        assert SourcePriority.DIGITAL_TEXT.value == 2

    def test_ocr_third(self):
        assert SourcePriority.OCR.value == 3

    def test_layout_fourth(self):
        assert SourcePriority.LAYOUT.value == 4

    def test_vlm_fifth(self):
        assert SourcePriority.VLM.value == 5

    def test_xml_higher_priority_than_digital(self):
        src_x = source_priority(ExtractionSource.XML)
        src_d = source_priority(ExtractionSource.DIGITAL_TEXT)
        assert src_x < src_d

    def test_digital_text_higher_priority_than_ocr(self):
        src_d = source_priority(ExtractionSource.DIGITAL_TEXT)
        src_o = source_priority(ExtractionSource.OCR)
        assert src_d < src_o

    def test_ocr_higher_priority_than_vlm(self):
        src_o = source_priority(ExtractionSource.OCR)
        src_v = source_priority(ExtractionSource.VLM)
        assert src_o < src_v


# ---------------------------------------------------------------------------
# Tests: resolve_field
# ---------------------------------------------------------------------------


class TestResolveField:
    def test_empty_candidates_returns_none(self):
        assert resolve_field("supplier.tax_id", []) is None

    def test_single_candidate_returns_it(self):
        c = _candidate("supplier.tax_id", "B12345678", 0.85)
        result = resolve_field("supplier.tax_id", [c])
        assert result is not None
        assert result.value == "B12345678"
        assert result.confidence == 0.85
        assert result.source == ExtractionSource.DIGITAL_TEXT

    def test_multiple_same_source_chooses_highest_confidence(self):
        c1 = _candidate("supplier.tax_id", "B12345678", 0.70)
        c2 = _candidate("supplier.tax_id", "B87654321", 0.90)
        result = resolve_field("supplier.tax_id", [c1, c2])
        assert result is not None
        assert result.value == "B87654321"
        assert result.confidence == 0.90

    def test_different_sources_chooses_higher_priority_source(self):
        # OCR candidate has higher confidence but lower source priority
        ocr_c = _candidate("supplier.tax_id", "B11111111", 0.95, ExtractionSource.OCR)
        dig_c = _candidate("supplier.tax_id", "B22222222", 0.80, ExtractionSource.DIGITAL_TEXT)
        result = resolve_field("supplier.tax_id", [ocr_c, dig_c])
        assert result is not None
        # DIGITAL_TEXT source has higher priority (lower number) than OCR
        assert result.value == "B22222222"
        assert result.source == ExtractionSource.DIGITAL_TEXT

    def test_xml_source_wins_over_all(self):
        xml_c = _candidate("supplier.tax_id", "B00000001", 0.60, ExtractionSource.XML)
        ocr_c = _candidate("supplier.tax_id", "B11111111", 0.95, ExtractionSource.OCR)
        dig_c = _candidate("supplier.tax_id", "B22222222", 0.80, ExtractionSource.DIGITAL_TEXT)
        result = resolve_field("supplier.tax_id", [ocr_c, xml_c, dig_c])
        assert result is not None
        assert result.source == ExtractionSource.XML
        assert result.value == "B00000001"

    def test_empty_value_filtered_out(self):
        c1 = _candidate("supplier.tax_id", "", 0.9)
        c2 = _candidate("supplier.tax_id", "B12345678", 0.5)
        result = resolve_field("supplier.tax_id", [c1, c2])
        assert result is not None
        assert result.value == "B12345678"

    def test_whitespace_value_filtered_out(self):
        c1 = _candidate("supplier.tax_id", "   ", 0.9)
        c2 = _candidate("supplier.tax_id", "B12345678", 0.5)
        result = resolve_field("supplier.tax_id", [c1, c2])
        assert result is not None
        assert result.value == "B12345678"

    def test_normalized_value_preserved(self):
        c = _candidate(
            "supplier.tax_id", "B-1234-5678", 0.85, normalized_value="B12345678"
        )
        result = resolve_field("supplier.tax_id", [c])
        assert result is not None
        assert result.normalized_value == "B12345678"


# ---------------------------------------------------------------------------
# Tests: resolve_all_fields
# ---------------------------------------------------------------------------


class TestResolveAllFields:
    def test_resolves_all_given_fields(self):
        cs = CandidateSet()
        cs.add(_candidate("invoice_data.number", "2024/001", 0.85))
        cs.add(_candidate("supplier.tax_id", "B12345678", 0.85))
        cs.add(_candidate("supplier.tax_id", "B87654321", 0.70))

        resolved = resolve_all_fields(
            cs,
            ["invoice_data.number", "supplier.tax_id"],
        )

        assert "invoice_data.number" in resolved
        assert "supplier.tax_id" in resolved
        assert resolved["invoice_data.number"].value == "2024/001"
        # Higher confidence wins
        assert resolved["supplier.tax_id"].value == "B12345678"

    def test_missing_field_not_in_result(self):
        cs = CandidateSet()
        cs.add(_candidate("invoice_data.number", "2024/001", 0.85))

        resolved = resolve_all_fields(cs, ["invoice_data.number", "nonexistent"])

        assert "invoice_data.number" in resolved
        assert "nonexistent" not in resolved


# ---------------------------------------------------------------------------
# Tests: confidence_per_field
# ---------------------------------------------------------------------------


class TestConfidencePerField:
    def test_returns_confidence_dict(self):
        rf1 = ResolvedField(
            field_name="invoice_data.number", value="2024/001", confidence=0.85
        )
        rf2 = ResolvedField(
            field_name="supplier.tax_id", value="B12345678", confidence=0.90
        )
        result = confidence_per_field({
            "invoice_data.number": rf1,
            "supplier.tax_id": rf2,
        })
        assert result["invoice_data.number"] == 0.85
        assert result["supplier.tax_id"] == 0.90


# ---------------------------------------------------------------------------
# Tests: global_confidence
# ---------------------------------------------------------------------------


class TestGlobalConfidence:
    def test_average_of_valid_confidences(self):
        field_confidences = {
            "invoice_data.number": 0.85,
            "supplier.tax_id": 0.90,
            "customer.tax_id": 0.75,
        }
        result = global_confidence(field_confidences)
        expected = (0.85 + 0.90 + 0.75) / 3
        assert abs(result - expected) < 1e-9

    def test_ignores_zero_confidences(self):
        field_confidences = {
            "invoice_data.number": 0.85,
            "supplier.tax_id": 0.0,
            "customer.tax_id": 0.75,
        }
        result = global_confidence(field_confidences)
        expected = (0.85 + 0.75) / 2
        assert abs(result - expected) < 1e-9

    def test_all_zeros_returns_zero(self):
        field_confidences = {
            "invoice_data.number": 0.0,
            "supplier.tax_id": 0.0,
        }
        result = global_confidence(field_confidences)
        assert result == 0.0

    def test_empty_dict_returns_zero(self):
        result = global_confidence({})
        assert result == 0.0


# ---------------------------------------------------------------------------
# Tests: needs_review
# ---------------------------------------------------------------------------


class TestNeedsReview:
    def test_fields_below_threshold_returned(self):
        field_confidences = {
            "invoice_data.number": 0.85,
            "supplier.tax_id": 0.60,
            "customer.tax_id": 0.50,
        }
        result = needs_review(field_confidences, threshold=0.7)
        assert "supplier.tax_id" in result
        assert "customer.tax_id" in result
        assert "invoice_data.number" not in result

    def test_exact_threshold_does_not_trigger_review(self):
        field_confidences = {"invoice_data.number": 0.7}
        result = needs_review(field_confidences, threshold=0.7)
        assert "invoice_data.number" not in result

    def test_empty_when_all_above_threshold(self):
        field_confidences = {
            "invoice_data.number": 0.85,
            "supplier.tax_id": 0.90,
        }
        result = needs_review(field_confidences, threshold=0.7)
        assert result == []

    def test_empty_when_all_zero(self):
        field_confidences = {
            "invoice_data.number": 0.0,
            "supplier.tax_id": 0.0,
        }
        result = needs_review(field_confidences, threshold=0.7)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: build_evidence
# ---------------------------------------------------------------------------


class TestBuildEvidence:
    def test_builds_evidence_from_candidate(self):
        block = NormalizedBlock(
            text="B12345678",
            bbox=(50.0, 100.0, 200.0, 130.0),
            page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        c = Candidate(
            field_name="supplier.tax_id",
            value="B12345678",
            confidence=0.85,
            block=block,
            page=1,
        )

        evidence = build_evidence(c)

        assert evidence.text == "B12345678"
        assert evidence.page == 1
        assert evidence.bbox == (50.0, 100.0, 200.0, 130.0)
        assert evidence.source == "digital_text"

    def test_builds_evidence_with_no_bbox(self):
        c = Candidate(
            field_name="supplier.tax_id",
            value="B12345678",
            confidence=0.85,
            block=None,
            page=1,
        )

        evidence = build_evidence(c)

        assert evidence.text == "B12345678"
        assert evidence.page == 1
        assert evidence.bbox is None


# ---------------------------------------------------------------------------
# Tests: build_all_evidences
# ---------------------------------------------------------------------------


class TestBuildAllEvidences:
    def test_builds_evidences_for_all_resolved_fields(self):
        block = NormalizedBlock(
            text="B12345678",
            bbox=(50, 100, 200, 130),
            page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        c1 = Candidate(
            field_name="supplier.tax_id",
            value="B12345678",
            confidence=0.85,
            block=block,
            page=1,
        )
        c2 = Candidate(
            field_name="invoice_data.number",
            value="2024/001",
            confidence=0.85,
            block=block,
            page=1,
        )
        rf1 = ResolvedField(
            field_name="supplier.tax_id",
            value="B12345678",
            confidence=0.85,
            source=ExtractionSource.DIGITAL_TEXT,
            evidence_candidate=c1,
        )
        rf2 = ResolvedField(
            field_name="invoice_data.number",
            value="2024/001",
            confidence=0.85,
            source=ExtractionSource.DIGITAL_TEXT,
            evidence_candidate=c2,
        )

        result = build_all_evidences({
            "supplier.tax_id": rf1,
            "invoice_data.number": rf2,
        })

        assert "supplier.tax_id" in result
        assert "invoice_data.number" in result
        assert result["supplier.tax_id"].text == "B12345678"
        assert result["invoice_data.number"].text == "2024/001"


# ---------------------------------------------------------------------------
# Tests: adjust_confidence_for_tax_id
# ---------------------------------------------------------------------------


class TestAdjustConfidenceForTaxId:
    def test_valid_tax_id_unchanged(self):
        # B12345674 is a valid CIF (control digit = 4 for B-type, digit control)
        c = _candidate("supplier.tax_id", "B12345674", 0.85)
        rf = ResolvedField(
            field_name="supplier.tax_id",
            value="B12345674",
            normalized_value="B12345674",
            confidence=0.85,
            evidence_candidate=c,
        )

        adjusted, warnings = adjust_confidence_for_tax_id(rf)

        assert adjusted.confidence == 0.85
        assert warnings == []

    def test_invalid_tax_id_reduces_confidence(self):
        # 00000001Q - NIF with wrong check digit, clearly invalid
        c = _candidate("supplier.tax_id", "00000001Q", 0.85)
        rf = ResolvedField(
            field_name="supplier.tax_id",
            value="00000001Q",
            normalized_value="00000001Q",
            confidence=0.85,
            evidence_candidate=c,
        )

        adjusted, warnings = adjust_confidence_for_tax_id(rf)

        assert adjusted.confidence == pytest.approx(0.425)
        assert any("inválido" in w for w in warnings)

    def test_uses_value_when_normalized_none(self):
        # 00000001Q - NIF with wrong check digit
        c = _candidate("supplier.tax_id", "00000001Q", 0.85)
        rf = ResolvedField(
            field_name="supplier.tax_id",
            value="00000001Q",
            normalized_value=None,
            confidence=0.85,
            evidence_candidate=c,
        )

        adjusted, warnings = adjust_confidence_for_tax_id(rf)

        assert adjusted.confidence == pytest.approx(0.425)


# ---------------------------------------------------------------------------
# Tests: resolve_document
# ---------------------------------------------------------------------------


class TestResolveDocument:
    def test_resolves_all_fields_and_returns_full_result(self):
        cs = CandidateSet()
        cs.add(_candidate("invoice_data.number", "2024/001", 0.85))
        cs.add(_candidate("supplier.tax_id", "B12345674", 0.85))

        result = resolve_document(cs, ["invoice_data.number", "supplier.tax_id"])

        assert isinstance(result, ResolutionResult)
        assert "invoice_data.number" in result.resolved_fields
        assert "supplier.tax_id" in result.resolved_fields
        assert "invoice_data.number" in result.field_confidences
        assert 0.0 <= result.global_confidence <= 1.0
        assert isinstance(result.needs_review, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.evidence, dict)

    def test_invalid_tax_id_adds_warning(self):
        cs = CandidateSet()
        cs.add(_candidate("supplier.tax_id", "00000001Q", 0.85))

        result = resolve_document(cs, ["supplier.tax_id"])

        assert len(result.warnings) > 0
        assert any("inválido" in w for w in result.warnings)

    def test_missing_field_results_in_zero_confidence(self):
        cs = CandidateSet()
        cs.add(_candidate("invoice_data.number", "2024/001", 0.85))

        result = resolve_document(cs, ["invoice_data.number", "supplier.tax_id"])

        assert "invoice_data.number" in result.field_confidences
        assert "supplier.tax_id" not in result.field_confidences
        assert "invoice_data.number" not in result.needs_review

    def test_low_confidence_triggers_needs_review(self):
        cs = CandidateSet()
        cs.add(_candidate("customer.legal_name", "ACME Corp", 0.55))

        result = resolve_document(cs, ["customer.legal_name"])

        assert "customer.legal_name" in result.needs_review

    def test_high_confidence_no_needs_review(self):
        cs = CandidateSet()
        cs.add(_candidate("invoice_data.number", "2024/001", 0.90))

        result = resolve_document(cs, ["invoice_data.number"])

        assert "invoice_data.number" not in result.needs_review

    def test_multiple_tax_ids_with_higher_priority_source(self):
        cs = CandidateSet()
        # OCR source candidate - higher confidence but lower priority
        ocr_c = _candidate("supplier.tax_id", "B11111111", 0.95, ExtractionSource.OCR)
        # Digital text candidate - lower confidence but higher priority
        dig_c = _candidate("supplier.tax_id", "B22222222", 0.80, ExtractionSource.DIGITAL_TEXT)
        cs.add(ocr_c)
        cs.add(dig_c)

        result = resolve_document(cs, ["supplier.tax_id"])

        assert result.resolved_fields["supplier.tax_id"].value == "B22222222"
        assert result.resolved_fields["supplier.tax_id"].source == ExtractionSource.DIGITAL_TEXT

    def test_empty_candidates_returns_empty_resolved(self):
        cs = CandidateSet()

        result = resolve_document(cs, ["invoice_data.number"])

        assert result.resolved_fields == {}
        assert result.global_confidence == 0.0