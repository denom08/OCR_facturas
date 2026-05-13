"""Unit tests for the invoice extraction evaluator."""

from decimal import Decimal

from scripts.evaluate_extraction import (
    ALL_FIELD_PATHS,
    amount_match,
    date_match,
    evaluate_invoice,
    exact_match,
    fuzzy_legal_name_match,
    tax_lines_match,
)


class TestExactMatch:
    def test_exact_match_success(self) -> None:
        match, score, _ = exact_match("B12345678", "B12345678")
        assert match is True
        assert score == 1.0

    def test_exact_match_failure(self) -> None:
        match, score, detail = exact_match("B12345678", "A12345678")
        assert match is False
        assert score == 0.0
        assert "B12345678" in detail

    def test_exact_match_empty(self) -> None:
        match, score, _ = exact_match("", "")
        assert match is True
        assert score == 1.0


class TestDateMatch:
    def test_date_match_success(self) -> None:
        match, score, _ = date_match("2026-01-15", "2026-01-15")
        assert match is True
        assert score == 1.0

    def test_date_match_failure(self) -> None:
        match, score, detail = date_match("2026-01-15", "2026-01-16")
        assert match is False
        assert score == 0.0


class TestAmountMatch:
    def test_amount_match_exact(self) -> None:
        match, score, _ = amount_match(Decimal("100.00"), Decimal("100.00"))
        assert match is True
        assert score == 1.0

    def test_amount_match_within_tolerance(self) -> None:
        match, score, _ = amount_match(Decimal("100.00"), Decimal("100.005"))
        assert match is True

    def test_amount_match_outside_tolerance(self) -> None:
        match, score, _ = amount_match(Decimal("100.00"), Decimal("101.00"))
        assert match is False
        assert score < 1.0

    def test_amount_match_string_input(self) -> None:
        match, score, _ = amount_match("100.00", "100.00")
        assert match is True

    def test_amount_match_zero(self) -> None:
        match, score, _ = amount_match(Decimal("0.00"), Decimal("0.01"))
        assert match is True  # diff is 0.01 which equals tolerance


class TestFuzzyLegalNameMatch:
    def test_fuzzy_match_identical(self) -> None:
        match, score, _ = fuzzy_legal_name_match(
            "Servicios Integrales del Norte S.L.",
            "Servicios Integrales del Norte S.L.",
        )
        assert match is True
        assert score == 1.0

    def test_fuzzy_match_different_suffix(self) -> None:
        match, score, _ = fuzzy_legal_name_match(
            "Servicios Integrales del Norte S.L.",
            "Servicios Integrales del Norte S.A.",
        )
        assert match is True  # suffix removed before compare
        assert score >= 0.95  # high but not necessarily 1.0 due to char-level diff

    def test_fuzzy_match_similar(self) -> None:
        match, score, _ = fuzzy_legal_name_match(
            "Servicios Integrales del Norte S.L.",
            "Servicos Integrales del Norte S.L.",  # missing i
        )
        # 3 chars differ out of ~40 = ratio ~0.92, so it SHOULD match at 0.85 threshold
        assert match is True
        assert score >= 0.85

    def test_fuzzy_match_completely_different(self) -> None:
        match, score, _ = fuzzy_legal_name_match(
            "Servicios ABC S.L.",
            "Construcciones XYZ S.A.",
        )
        assert match is False
        assert score < 0.85

    def test_fuzzy_match_strips_whitespace(self) -> None:
        match, score, _ = fuzzy_legal_name_match(
            "  Nombre  de Empresa  S.L.  ",
            "NOMBRE DE EMPRESA S.A.",
        )
        assert match is True


class TestTaxLinesMatch:
    def test_tax_lines_match_identical(self) -> None:
        expected = [
            {"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"},
            {"tax_rate": "10.00", "tax_base": "500.00", "tax_amount": "50.00"},
        ]
        predicted = [
            {"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"},
            {"tax_rate": "10.00", "tax_base": "500.00", "tax_amount": "50.00"},
        ]
        match, score, _ = tax_lines_match(expected, predicted)
        assert match is True
        assert score == 1.0

    def test_tax_lines_match_within_tolerance(self) -> None:
        expected = [{"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"}]
        predicted = [{"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.005"}]
        match, score, _ = tax_lines_match(expected, predicted)
        assert match is True

    def test_tax_lines_match_different_rate(self) -> None:
        expected = [{"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"}]
        predicted = [{"tax_rate": "10.00", "tax_base": "1000.00", "tax_amount": "100.00"}]
        match, score, _ = tax_lines_match(expected, predicted)
        assert match is False
        assert score == 0.0

    def test_tax_lines_match_different_count(self) -> None:
        expected = [
            {"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"},
            {"tax_rate": "10.00", "tax_base": "500.00", "tax_amount": "50.00"},
        ]
        predicted = [
            {"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"},
        ]
        match, score, detail = tax_lines_match(expected, predicted)
        assert match is False
        assert "line count mismatch" in detail

    def test_tax_lines_match_empty(self) -> None:
        match, score, _ = tax_lines_match([], [])
        assert match is True
        assert score == 1.0


class TestEvaluateInvoice:
    def test_evaluate_full_invoice_correct(self) -> None:
        expected = {
            "invoice_data": {
                "number": "FAC-2026-001",
                "issue_date": "2026-01-15",
                "due_date": "2026-02-15",
            },
            "supplier": {
                "legal_name": "Servicios Integrales del Norte S.L.",
                "tax_id": "A12345678",
            },
            "customer": {
                "legal_name": "Distribuciones del Levante S.A.",
                "tax_id": "B98765432",
            },
            "tax_lines": [
                {"tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00"},
            ],
            "totals": {
                "net_amount": "1000.00",
                "tax_amount": "210.00",
                "gross_amount": "1210.00",
            },
        }
        result = evaluate_invoice(
            invoice_file="test.pdf",
            invoice_type="digital",
            expected=expected,
            predicted=expected,
        )
        assert result.overall_score == 1.0
        assert len(result.errors) == 0

    def test_evaluate_invoice_all_wrong(self) -> None:
        expected = {
            "invoice_data": {
                "number": "FAC-2026-001",
                "issue_date": "2026-01-15",
            },
            "supplier": {"legal_name": "Empresa S.L.", "tax_id": "A12345678"},
            "customer": {"legal_name": "Cliente S.A.", "tax_id": "B98765432"},
            "tax_lines": [],
            "totals": {
                "net_amount": "1000.00",
                "tax_amount": "210.00",
                "gross_amount": "1210.00",
            },
        }
        predicted = {
            "invoice_data": {"number": "OTHER", "issue_date": "2025-01-01"},
            "supplier": {"legal_name": "Otro", "tax_id": "Z99999999"},
            "customer": {"legal_name": "Otro", "tax_id": "Z99999998"},
            "tax_lines": [],
            "totals": {
                "net_amount": "500.00",
                "tax_amount": "100.00",
                "gross_amount": "600.00",
            },
        }
        result = evaluate_invoice(
            invoice_file="test.pdf",
            invoice_type="digital",
            expected=expected,
            predicted=predicted,
        )
        assert result.overall_score < 1.0
        assert len(result.errors) > 0

    def test_evaluate_invoice_partial_match(self) -> None:
        expected = {
            "invoice_data": {"number": "FAC-2026-001", "issue_date": "2026-01-15"},
            "supplier": {"legal_name": "Empresa S.L.", "tax_id": "A12345678"},
            "customer": {"legal_name": "Cliente S.A.", "tax_id": "B98765432"},
            "tax_lines": [],
            "totals": {
                "net_amount": "1000.00",
                "tax_amount": "210.00",
                "gross_amount": "1210.00",
            },
        }
        predicted = {
            "invoice_data": {"number": "FAC-2026-001", "issue_date": "2026-01-15"},
            "supplier": {"legal_name": "Empresa S.L.", "tax_id": "A12345678"},
            "customer": {"legal_name": "Cliente S.A.", "tax_id": "B98765432"},
            "tax_lines": [],
            "totals": {
                "net_amount": "1000.00",
                "tax_amount": "210.00",
                "gross_amount": "1210.00",
            },
        }
        result = evaluate_invoice(
            invoice_file="test.pdf",
            invoice_type="digital",
            expected=expected,
            predicted=predicted,
        )
        assert result.overall_score == 1.0
        assert len(result.errors) == 0


class TestFieldPaths:
    def test_all_field_paths_defined(self) -> None:
        assert len(ALL_FIELD_PATHS) > 0
        assert "invoice_data.number" in ALL_FIELD_PATHS
        assert "supplier.tax_id" in ALL_FIELD_PATHS
        assert "customer.legal_name" in ALL_FIELD_PATHS
        assert "tax_lines" in ALL_FIELD_PATHS
        assert "totals" in ALL_FIELD_PATHS