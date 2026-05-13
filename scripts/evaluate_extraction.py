"""
Evaluator for invoice extraction results.

Compares predicted JSON against expected ground truth using field-specific metrics:
- CIF/NIF: exact match
- Dates: exact match (ISO format)
- Amounts: tolerance-based match (0.01 EUR)
- Legal name: fuzzy/normalized match
- Tax lines: structural match with tolerance
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FieldResult:
    field_path: str
    expected: str | Decimal | list | dict | object | None
    predicted: str | Decimal | list | dict | object | None
    match: bool
    metric: str  # e.g. "exact", "tolerance", "fuzzy", "structure"
    score: float  # 0.0-1.0
    detail: str = ""


@dataclass
class InvoiceResult:
    invoice_file: str
    invoice_type: str
    field_results: list[FieldResult] = field(default_factory=list)
    overall_score: float = 0.0

    @property
    def errors(self) -> list[FieldResult]:
        return [fr for fr in self.field_results if not fr.match]


@dataclass
class EvaluationReport:
    results: list[InvoiceResult] = field(default_factory=list)
    per_type_errors: dict[str, int] = field(default_factory=dict)
    per_type_totals: dict[str, int] = field(default_factory=dict)

    def global_accuracy(self) -> float:
        """Weighted accuracy across all fields and invoices."""
        if not self.results:
            return 0.0
        total = sum(r.overall_score for r in self.results)
        return total / len(self.results)

    def field_accuracy(self, field_path: str) -> float:
        """Accuracy for a specific field path."""
        matches = sum(
            1 for r in self.results
            for fr in r.field_results
            if fr.field_path == field_path and fr.match
        )
        total = sum(
            1 for r in self.results
            for fr in r.field_results
            if fr.field_path == field_path
        )
        return (matches / total) if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Core matching functions
# ---------------------------------------------------------------------------

MONEY_TOLERANCE = Decimal("0.01")


def exact_match(expected: str, predicted: str) -> tuple[bool, float, str]:
    if expected == predicted:
        return True, 1.0, ""
    return False, 0.0, f"expected {expected!r}, got {predicted!r}"


def date_match(expected: str, predicted: str) -> tuple[bool, float, str]:
    """Both dates in ISO format YYYY-MM-DD."""
    return exact_match(expected, predicted)


def amount_match(
    expected: Decimal | str,
    predicted: Decimal | str,
    tolerance: Decimal = MONEY_TOLERANCE,
) -> tuple[bool, float, str]:
    """Match amounts with configurable tolerance."""
    try:
        exp = Decimal(str(expected))
        pred = Decimal(str(predicted))
    except Exception as exc:
        return False, 0.0, f"decimal parse error: {exc}"

    diff = abs(exp - pred)
    if diff <= tolerance:
        return True, 1.0, ""
    # Use Decimal arithmetic for score to avoid float/Decimal mixing
    score = max(Decimal("0"), Decimal("1") - (diff / exp)) if exp != 0 else Decimal("0")
    return False, float(score), f"expected {exp}, got {pred}, diff {diff}"


def fuzzy_legal_name_match(
    expected: str, predicted: str, threshold: float = 0.85
) -> tuple[bool, float, str]:
    """Normalize and compare legal names using similarity ratio."""
    norm_exp = _normalize_legal_name(expected)
    norm_pred = _normalize_legal_name(predicted)

    if norm_exp == norm_pred:
        return True, 1.0, ""

    ratio = SequenceMatcher(None, norm_exp, norm_pred).ratio()
    match = ratio >= threshold
    detail = f"similarity {ratio:.2%}" if not match else ""
    return match, ratio, detail


def _normalize_legal_name(name: str) -> str:
    """Remove common suffixes and normalize for comparison."""
    import re

    cleaned = re.sub(
        r"\b(S\.L\.|S\.A\.|S\.L\.L\.|Ltd\.|Inc\.|Corp\.)\b", "", name, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"[\s\-.,;]+", " ", cleaned).strip().upper()
    return cleaned


def tax_lines_match(
    expected: list[dict],
    predicted: list[dict],
    tolerance: Decimal = MONEY_TOLERANCE,
) -> tuple[bool, float, str]:
    """
    Compare tax lines structure:
    - Same number of lines
    - Each line: tax_rate exact, tax_base and tax_amount within tolerance
    """
    if len(expected) != len(predicted):
        return (
            False,
            0.0,
            f"line count mismatch: expected {len(expected)}, got {len(predicted)}",
        )

    if not expected:
        return True, 1.0, ""

    scores: list[float] = []
    for exp_line, pred_line in zip(expected, predicted, strict=True):
        rate_exp = str(exp_line.get("tax_rate", ""))
        rate_pred = str(pred_line.get("tax_rate", ""))
        if rate_exp != rate_pred:
            scores.append(0.0)
            continue

        try:
            base_exp = Decimal(str(exp_line.get("tax_base", "0")))
            base_pred = Decimal(str(pred_line.get("tax_base", "0")))
            amt_exp = Decimal(str(exp_line.get("tax_amount", "0")))
            amt_pred = Decimal(str(pred_line.get("tax_amount", "0")))
        except Exception:
            scores.append(0.0)
            continue

        base_ok = abs(base_exp - base_pred) <= tolerance
        amt_ok = abs(amt_exp - amt_pred) <= tolerance
        line_score = 1.0 if (base_ok and amt_ok) else 0.0
        scores.append(line_score)

    avg_score = sum(scores) / len(scores) if scores else 0.0
    all_ok = all(s == 1.0 for s in scores)
    detail = "" if all_ok else f"avg_score={avg_score:.2%}"
    return all_ok, avg_score, detail


# ---------------------------------------------------------------------------
# Field evaluation dispatcher
# ---------------------------------------------------------------------------

_FIELD_EVALUATORS: dict[str, callable] = {}


def register_evaluator(field_path: str) -> callable:
    """Decorator to register a field evaluator."""
    def decorator(func: callable) -> callable:
        _FIELD_EVALUATORS[field_path] = func
        return func
    return decorator


def _get_nested(data: dict, field_path: str):
    """Get value from nested dict using dot notation (e.g. 'invoice_data.number')."""
    keys = field_path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def evaluate_field(
    field_path: str,
    expected: dict,
    predicted: dict,
) -> FieldResult:
    """Evaluate a single field using registered evaluators or fallback."""
    exp_value = _get_nested(expected, field_path)
    pred_value = _get_nested(predicted, field_path)

    # Try registered evaluator first
    if field_path in _FIELD_EVALUATORS:
        match, score, detail = _FIELD_EVALUATORS[field_path](exp_value, pred_value)
        return FieldResult(
            field_path=field_path,
            expected=exp_value,
            predicted=pred_value,
            match=match,
            metric=field_path,
            score=score,
            detail=detail,
        )

    # Fallback: exact match for strings/dates, amount match for Decimals
    if exp_value is None and pred_value is None:
        return FieldResult(
            field_path=field_path, expected=exp_value, predicted=pred_value,
            match=True, metric="exact", score=1.0, detail="both null",
        )

    if isinstance(exp_value, (str,)) and isinstance(pred_value, str):
        match, score, detail = exact_match(exp_value, pred_value)
        return FieldResult(
            field_path=field_path, expected=exp_value, predicted=pred_value,
            match=match, metric="exact", score=score, detail=detail,
        )

    if (
        isinstance(exp_value, (Decimal, int, float))
        or isinstance(pred_value, (Decimal, int, float))
    ):
        match, score, detail = amount_match(exp_value, pred_value)
        return FieldResult(
            field_path=field_path, expected=exp_value, predicted=pred_value,
            match=match, metric="tolerance", score=score, detail=detail,
        )

    # Generic equality
    match = exp_value == pred_value
    return FieldResult(
        field_path=field_path, expected=exp_value, predicted=pred_value,
        match=match, metric="structural", score=1.0 if match else 0.0,
        detail="" if match else f"mismatch: {type(exp_value)} vs {type(pred_value)}",
    )


# ---------------------------------------------------------------------------
# Specific evaluators
# ---------------------------------------------------------------------------

def _eval_supplier_tax_id(exp: dict | None, pred: dict | None) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return exact_match(exp_val, pred_val)


def _eval_customer_tax_id(exp: dict | None, pred: dict | None) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return exact_match(exp_val, pred_val)


def _eval_invoice_number(exp: dict | None, pred: dict | None) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return exact_match(exp_val, pred_val)


def _eval_issue_date(exp: dict | None, pred: dict | None) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return date_match(exp_val, pred_val)


def _eval_supplier_legal_name(
    exp: dict | None, pred: dict | None
) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return fuzzy_legal_name_match(exp_val, pred_val)


def _eval_customer_legal_name(
    exp: dict | None, pred: dict | None
) -> tuple[bool, float, str]:
    exp_val = str(exp) if exp is not None else ""
    pred_val = str(pred) if pred is not None else ""
    return fuzzy_legal_name_match(exp_val, pred_val)


def _eval_totals(exp: dict | None, pred: dict | None) -> tuple[bool, float, str]:
    """Evaluate all totals fields with tolerance."""
    exp_totals = exp if isinstance(exp, dict) else {}
    pred_totals = pred if isinstance(pred, dict) else {}

    fields = ["net_amount", "tax_amount", "gross_amount"]
    scores = []
    for f in fields:
        e = exp_totals.get(f, "0") if exp_totals else "0"
        p = pred_totals.get(f, "0") if pred_totals else "0"
        ok, score, _ = amount_match(e, p)
        scores.append(score)

    avg = sum(scores) / len(scores) if scores else 0.0
    all_ok = all(s == 1.0 for s in scores)
    return all_ok, avg, ""


def _eval_tax_lines(
    exp: dict | None, pred: dict | None
) -> tuple[bool, float, str]:
    exp_lines = exp if isinstance(exp, list) else []
    pred_lines = pred if isinstance(pred, list) else []
    return tax_lines_match(exp_lines, pred_lines)


# Register specific evaluators
_FIELD_EVALUATORS["supplier.tax_id"] = _eval_supplier_tax_id
_FIELD_EVALUATORS["customer.tax_id"] = _eval_customer_tax_id
_FIELD_EVALUATORS["supplier.legal_name"] = _eval_supplier_legal_name
_FIELD_EVALUATORS["customer.legal_name"] = _eval_customer_legal_name
_FIELD_EVALUATORS["invoice_data.number"] = _eval_invoice_number
_FIELD_EVALUATORS["invoice_data.issue_date"] = _eval_issue_date
_FIELD_EVALUATORS["totals"] = _eval_totals
_FIELD_EVALUATORS["tax_lines"] = _eval_tax_lines


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------

ALL_FIELD_PATHS = [
    "invoice_data.number",
    "invoice_data.issue_date",
    "supplier.legal_name",
    "supplier.tax_id",
    "customer.legal_name",
    "customer.tax_id",
    "tax_lines",
    "totals",
]


def evaluate_invoice(
    invoice_file: str,
    invoice_type: str,
    expected: dict,
    predicted: dict,
) -> InvoiceResult:
    """Evaluate a single invoice prediction against its ground truth."""
    results: list[FieldResult] = []

    for field_path in ALL_FIELD_PATHS:
        fr = evaluate_field(field_path, expected, predicted)
        results.append(fr)

    overall = (
        sum(fr.score for fr in results) / len(results)
        if results
        else 0.0
    )

    return InvoiceResult(
        invoice_file=invoice_file,
        invoice_type=invoice_type,
        field_results=results,
        overall_score=overall,
    )


def load_ground_truth(path: str | Path) -> list[dict]:
    """Load ground truth JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Ground truth not found: {p}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_predicted(path: str | Path) -> dict:
    """Load a single predicted JSON result file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Predicted result not found: {p}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def evaluate_dataset(
    ground_truth_path: str | Path,
    predictions_dir: str | Path,
    invoice_type: str = "digital",
) -> EvaluationReport:
    """
    Evaluate all predictions in `predictions_dir` against ground truth.

    Ground truth format (list of dicts with invoice_file + expected):
        [
          {"invoice_file": "...", "invoice_type": "...", "expected": {...}},
          ...
        ]

    Predictions: one JSON file per invoice in `predictions_dir`,
    named after invoice_file (e.g. "digital_synth_001.pdf" -> "digital_synth_001.json").
    """
    gt_path = Path(ground_truth_path)
    pred_dir = Path(predictions_dir)

    gt_data = load_ground_truth(gt_path)
    results: list[InvoiceResult] = []
    per_type_errors: dict[str, int] = {}
    per_type_totals: dict[str, int] = {}

    for entry in gt_data:
        invoice_file = entry["invoice_file"]
        expected = entry["expected"]

        pred_file = pred_dir / Path(invoice_file).with_suffix(".json")
        if not pred_file.exists():
            # No prediction -> all fields wrong
            pred_data: dict = {}
        else:
            pred_data = load_predicted(pred_file)

        inv_result = evaluate_invoice(
            invoice_file=invoice_file,
            invoice_type=invoice_type,
            expected=expected,
            predicted=pred_data,
        )
        results.append(inv_result)

        # Aggregate per type
        inv_type = entry.get("invoice_type", invoice_type)
        per_type_totals[inv_type] = per_type_totals.get(inv_type, 0) + len(inv_result.field_results)
        per_type_errors[inv_type] = per_type_errors.get(inv_type, 0) + len(inv_result.errors)

    return EvaluationReport(
        results=results,
        per_type_errors=per_type_errors,
        per_type_totals=per_type_totals,
    )


def print_report(report: EvaluationReport, verbose: bool = False) -> None:
    """Print human-readable evaluation report."""
    print("\n" + "=" * 70)
    print("EVALUATION REPORT")
    print("=" * 70)

    print("\n## Per-type Error Summary")
    for inv_type, total in sorted(report.per_type_totals):
        errors = report.per_type_errors.get(inv_type, 0)
        acc = ((total - errors) / total * 100) if total > 0 else 0.0
        print(f"  {inv_type:<12} {total:>6} fields  {errors:>5} errors  accuracy: {acc:>6.1f}%")

    print("\n## Per-invoice Results")
    for result in report.results:
        status = "OK" if not result.errors else f"ERR({len(result.errors)})"
        print(f"  [{status}] {result.invoice_file:<40} score: {result.overall_score:.2%}")

        if verbose and result.errors:
            print("    Errors:")
            for fr in result.errors:
                print(f"      - {fr.field_path}: {fr.detail}")

    print("\n## Field-level Accuracy")
    for field_path in ALL_FIELD_PATHS:
        acc = report.field_accuracy(field_path)
        print(f"  {field_path:<35} {acc:>6.1%}")

    print(f"\n## Global Accuracy: {report.global_accuracy():.2%}")
    print("=" * 70 + "\n")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate invoice extraction results")
    parser.add_argument(
        "--ground-truth", "-g",
        required=True,
        help="Path to ground truth JSON file",
    )
    parser.add_argument(
        "--predictions", "-p",
        required=True,
        help="Directory containing predicted JSON files",
    )
    parser.add_argument(
        "--type", "-t",
        default="digital",
        help="Invoice type (digital, hybrid, scanned)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed errors per invoice",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write JSON report to file",
    )

    args = parser.parse_args()

    try:
        report = evaluate_dataset(
            ground_truth_path=args.ground_truth,
            predictions_dir=args.predictions,
            invoice_type=args.type,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "global_accuracy": report.global_accuracy(),
                    "per_type_errors": report.per_type_errors,
                    "per_type_totals": report.per_type_totals,
                    "results": [
                        {
                            "invoice_file": r.invoice_file,
                            "invoice_type": r.invoice_type,
                            "overall_score": r.overall_score,
                            "field_results": [
                                {
                                    "field_path": fr.field_path,
                                    "match": fr.match,
                                    "score": fr.score,
                                    "detail": fr.detail,
                                }
                                for fr in r.field_results
                            ],
                        }
                        for r in report.results
                    ],
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"JSON report written to {output_path}")

    print_report(report, verbose=args.verbose)

    # Exit code: 0 if all invoices have no errors, 1 otherwise
    has_errors = any(r.errors for r in report.results)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()