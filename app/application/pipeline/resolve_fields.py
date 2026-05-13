"""Resolución de campos, conflicto de candidatos y cálculo de confianza.

Construido encima del pipeline digital (B4). Gestiona:
- Prioridades de fuentes: XML > digital_text > OCR > layout > VLM
- Resolución de conflictos entre candidatos del mismo campo
- Cálculo de confianza por campo
- Cálculo de confianza global
- Generación de needs_review
- Asociación de evidencias

Extensible para fuentes futuras (OCR, VLM) sin cambiar la arquitectura.
"""

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any

from app.api.schemas.invoices import Evidence
from app.application.pipeline.extract_candidates import (
    Candidate,
    CandidateSet,
)
from app.application.pipeline.normalize_document import ExtractionSource
from app.domain.services.tax_id_validator import is_valid_tax_id

# ---------------------------------------------------------------------------
# Prioridades de fuente
# ---------------------------------------------------------------------------


class SourcePriority(IntEnum):
    """Menor número = mayor prioridad."""

    XML = 1
    DIGITAL_TEXT = 2
    OCR = 3
    LAYOUT = 4
    VLM = 5


def source_priority(source: ExtractionSource) -> int:
    return SourcePriority[source.name].value


# ---------------------------------------------------------------------------
# Resultado resuelto
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedField:
    """Un campo resolved con valor, confianza, fuente y evidencia."""

    field_name: str
    value: str
    normalized_value: str | None = None
    confidence: float = 0.5
    source: ExtractionSource = ExtractionSource.DIGITAL_TEXT
    evidence_candidate: Candidate | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "confidence": self.confidence,
            "source": self.source.value,
        }


# ---------------------------------------------------------------------------
# Resolución de conflictos
# ---------------------------------------------------------------------------


def _candidate_source(c: Candidate) -> ExtractionSource:
    """Extrae la fuente de un candidato desde su bloque."""
    return c.block.source if c.block else ExtractionSource.DIGITAL_TEXT


def _best_from_source(src_candidates: list[Candidate]) -> Candidate:
    """Mejor candidato de una lista (mayor confianza)."""
    return max(src_candidates, key=lambda c: c.confidence)


def resolve_field(
    field_name: str,
    candidates: list[Candidate],
    *,
    source_priority_fn=source_priority,
) -> ResolvedField | None:
    """Resuelve un campo desde una lista de candidatos.

    Estrategia:
    1. Filtrar candidatos válidos (value no vacío).
    2. Si solo hay uno, usarlo.
    3. Si hay varios del mismo source, elegir el de mayor confianza.
    4. Si hay de fuentes distintas, priorizar por SourcePriority.
    5. En caso de mismo source y misma confianza, usar el primero encontrado.
    """
    valid = [c for c in candidates if c.value and c.value.strip()]
    if not valid:
        return None

    # Agrupar por fuente
    by_source: dict[ExtractionSource, list[Candidate]] = {}
    for c in valid:
        src = _candidate_source(c)
        by_source.setdefault(src, []).append(c)

    # Recoger prioridades únicas presentes en los candidatos válidos
    all_priorities = sorted(
        set(source_priority_fn(_candidate_source(c)) for c in valid)
    )
    for priority in all_priorities:
        for src, src_candidates in by_source.items():
            if source_priority_fn(src) == priority:
                best = _best_from_source(src_candidates)
                return ResolvedField(
                    field_name=field_name,
                    value=best.value,
                    normalized_value=best.normalized_value,
                    confidence=best.confidence,
                    source=src,
                    evidence_candidate=best,
                )

    return None


def resolve_all_fields(
    candidate_set: CandidateSet,
    fields_to_resolve: list[str],
) -> dict[str, ResolvedField]:
    """Resuelve todos los campos dados usando la estrategia de resolución."""
    resolved: dict[str, ResolvedField] = {}
    for fname in fields_to_resolve:
        candidates = candidate_set.by_field(fname)
        result = resolve_field(fname, candidates)
        if result is not None:
            resolved[fname] = result
    return resolved


# ---------------------------------------------------------------------------
# Cálculo de confianza
# ---------------------------------------------------------------------------


def confidence_per_field(resolved: dict[str, ResolvedField]) -> dict[str, float]:
    """Calcula confianza por campo desde los campos resueltos."""
    return {fname: rf.confidence for fname, rf in resolved.items()}


def global_confidence(field_confidences: dict[str, float]) -> float:
    """Calcula confianza global como promedio de confidences no nulas."""
    valid = [v for v in field_confidences.values() if v > 0]
    if not valid:
        return 0.0
    return sum(valid) / len(valid)


def needs_review(
    field_confidences: dict[str, float],
    threshold: float = 0.7,
) -> list[str]:
    """Genera lista de campos que necesitan revisión humana.

    Only flags fields with non-zero confidence below threshold.
    Zero-confidence fields mean the field is missing — they are not flagged
    as needing review because they are already handled as errors elsewhere.
    """
    return [fname for fname, conf in field_confidences.items() if 0 < conf < threshold]


# ---------------------------------------------------------------------------
# Construcción de evidencias
# ---------------------------------------------------------------------------


def build_evidence(c: Candidate) -> Evidence:
    """Construye una evidencia desde un candidato."""
    src = c.block.source if c.block else ExtractionSource.DIGITAL_TEXT
    return Evidence(
        text=c.value,
        page=c.page,
        bbox=c.block.bbox if c.block else None,
        source=src.value,
    )


def build_all_evidences(
    resolved: dict[str, ResolvedField],
) -> dict[str, Evidence]:
    """Construye mapa de evidencias para todos los campos resueltos."""
    evidence: dict[str, Evidence] = {}
    for fname, rf in resolved.items():
        if rf.evidence_candidate is not None:
            evidence[fname] = build_evidence(rf.evidence_candidate)
    return evidence


# ---------------------------------------------------------------------------
# Validación de tax_id (para ajustar confianza)
# ---------------------------------------------------------------------------


def adjust_confidence_for_tax_id(
    resolved_field: ResolvedField,
) -> tuple[ResolvedField, list[str]]:
    """Adjust confidence if tax_id is invalid.

    Returns (adjusted_field, warnings).
    """
    warnings: list[str] = []
    if resolved_field.normalized_value:
        tax_id = resolved_field.normalized_value
    else:
        tax_id = resolved_field.value

    if not is_valid_tax_id(tax_id):
        # Reducir confianza al 50%
        new_confidence = resolved_field.confidence * 0.5
        adjusted = replace(resolved_field, confidence=new_confidence)
        warnings.append(f"Tax ID potencialmente inválido: {tax_id}")
        return adjusted, warnings

    return resolved_field, warnings


# ---------------------------------------------------------------------------
# Resolución completa de documento (para uso en pipeline)
# ---------------------------------------------------------------------------


@dataclass
class ResolutionResult:
    """Resultado completo de la resolución de campos de un documento."""

    resolved_fields: dict[str, ResolvedField]
    field_confidences: dict[str, float]
    global_confidence: float
    needs_review: list[str]
    warnings: list[str]
    evidence: dict[str, Evidence]


def resolve_document(
    candidate_set: CandidateSet,
    fields_to_resolve: list[str],
) -> ResolutionResult:
    """Resuelve todos los campos de un documento.

    Aplica prioridades de fuente, resuelve conflictos, calcula confianza
    y genera evidencias. No modifica el CandidateSet original.
    """
    # Resolver campos
    resolved = resolve_all_fields(candidate_set, fields_to_resolve)

    # Validar y ajustar confidence de tax_ids
    final_resolved: dict[str, ResolvedField] = {}
    all_warnings: list[str] = []
    for fname, rf in resolved.items():
        if "tax_id" in fname:
            adjusted_rf, wf = adjust_confidence_for_tax_id(rf)
            final_resolved[fname] = adjusted_rf
            all_warnings.extend(wf)
        else:
            final_resolved[fname] = rf

    # Confianza por campo
    fconf = confidence_per_field(final_resolved)

    # Confianza global
    global_conf = global_confidence(fconf)

    # Needs review
    review = needs_review(fconf)

    # Evidencias
    ev = build_all_evidences(final_resolved)

    return ResolutionResult(
        resolved_fields=final_resolved,
        field_confidences=fconf,
        global_confidence=global_conf,
        needs_review=review,
        warnings=all_warnings,
        evidence=ev,
    )