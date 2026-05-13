"""Reglas de invocación del VLM para casos complejos (B9).

El VLM se invoca SOLO cuando las fuentes deterministas (digital, OCR, layout)
no han podido resolver campos obligatorios o la confianza es baja.

El VLM NUNCA sustituye a los validadores de dominio (B2) ni al resolutor (B8).
Solo propone candidatos que deben pasar por validación.

Reglas de decisión:
1. Campos obligatorios faltantes: tax_id, invoice_data.number, invoice_data.issue_date
2. Baja confianza global (< 0.6) o de campos clave
3. Factura escaneada compleja con baja calidad OCR
4. Tabla fiscal no resuelta (layout no disponible o tax_lines vacías)
5. Proveedor/cliente sin resolver en documento híbrido/escaneado

El VLM puede proponer valores pero el dominio decide si se aceptan.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.application.ports.invoice_extractor import VlmExtractionResult

if TYPE_CHECKING:
    from app.application.pipeline.resolve_fields import ResolutionResult


@dataclass(frozen=True)
class VlmInvocationReason:
    """Razón por la que se invocó el VLM."""

    code: str  # missing_field | low_confidence | complex_scanned | tax_table_unresolved
    detail: str


# ---------------------------------------------------------------------------
# Condiciones de invocación
# ---------------------------------------------------------------------------

# Campos obligatorios que justifican invocación de VLM
_REQUIRED_FIELDS_INVOCATION = frozenset([
    "invoice_data.number",
    "invoice_data.issue_date",
    "supplier.tax_id",
    "customer.tax_id",
])

# Umbral de confianza bajo para invocar VLM en campos clave
_LOW_CONFIDENCE_THRESHOLD = 0.6

# Umbral de confianza global bajo
_GLOBAL_CONFIDENCE_THRESHOLD = 0.6

# Confianza mínima para no invocar VLM en campos de tax_lines
_TAX_LINES_MIN_CONFIDENCE = 0.7


def should_invoke_vlm(
    resolved_result: "ResolutionResult | None" = None,
    *,
    missing_fields: list[str] | None = None,
    low_confidence_fields: list[str] | None = None,
    global_confidence: float | None = None,
    is_scanned: bool = False,
    tax_lines_unresolved: bool = False,
    ocr_quality_low: bool = False,
) -> tuple[bool, list[VlmInvocationReason]]:
    """Determina si debe invocarse el VLM según las condiciones actuales.

    Args:
        resolved_result: Resultado de resolve_document (B8). Si está disponible,
            se extraen missing_fields, low_confidence_fields y global_confidence.
        missing_fields: Lista de campos obligatorios faltantes (override).
        low_confidence_fields: Lista de campos con baja confianza (override).
        global_confidence: Confianza global (override).
        is_scanned: True si el PDF es escaneado o híbrido.
        tax_lines_unresolved: True si las líneas de IVA no se pudieron resolver.
        ocr_quality_low: True si el OCR tiene baja calidad (pocos bloques detectados).

    Returns:
        Tuple de (should_invoke, reasons). should_invoke=True si el VLM debe llamado.
    """
    reasons: list[VlmInvocationReason] = []

    # Extraer desde resolved_result si está disponible
    if resolved_result is not None:
        missing_fields = list(resolved_result.resolved_fields.keys())
        global_confidence_val = resolved_result.global_confidence
        # Los campos no resueltos son los ausentes en resolved_fields
        all_required = list(_REQUIRED_FIELDS_INVOCATION)
        missing_fields = [f for f in all_required if f not in resolved_result.resolved_fields]
        low_confidence_fields = list(resolved_result.needs_review)

        if global_confidence is None:
            global_confidence = global_confidence_val

    # Normalizar a listas vacías si son None
    missing_fields = missing_fields or []
    low_confidence_fields = low_confidence_fields or []

    # Regla 1: campos obligatorios faltantes
    critical_missing = [f for f in missing_fields if f in _REQUIRED_FIELDS_INVOCATION]
    if critical_missing:
        reasons.append(
            VlmInvocationReason(
                code="missing_field",
                detail=f"Campos obligatorios faltantes: {', '.join(critical_missing)}",
            )
        )

    # Regla 2: baja confianza global
    if global_confidence is not None and global_confidence < _GLOBAL_CONFIDENCE_THRESHOLD:
        reasons.append(
            VlmInvocationReason(
                code="low_confidence",
                detail=f"Confianza global {global_confidence:.2f} < {_GLOBAL_CONFIDENCE_THRESHOLD}",
            )
        )

    # Regla 3: baja confianza en campos clave
    key_low_conf = [f for f in low_confidence_fields if f in _REQUIRED_FIELDS_INVOCATION]
    if key_low_conf:
        reasons.append(
            VlmInvocationReason(
                code="low_confidence_field",
                detail=f"Campos clave con baja confianza: {', '.join(key_low_conf)}",
            )
        )

    # Regla 4: factura escaneada compleja
    if is_scanned and tax_lines_unresolved:
        reasons.append(
            VlmInvocationReason(
                code="complex_scanned",
                detail="Factura escaneada con tabla fiscal no resuelta",
            )
        )

    # Regla 5: tax_lines no resueltas en documento con IVA múltiple
    if tax_lines_unresolved:
        reasons.append(
            VlmInvocationReason(
                code="tax_table_unresolved",
                detail="Tabla fiscal no resuelta por layout/OCR",
            )
        )

    # Regla 6: OCR de baja calidad
    if ocr_quality_low:
        reasons.append(
            VlmInvocationReason(
                code="low_ocr_quality",
                detail="OCR con baja calidad (pocos bloques detectados)",
            )
        )

    should_invoke = len(reasons) > 0
    return should_invoke, reasons


def get_vlm_candidates_from_result(
    vlm_result: "VlmExtractionResult",
    page: int = 1,
) -> list:
    """Convierte VlmExtractionResult en candidatos para el resolutor (B8).

    El VLM SOLO propone candidatos. Estos candidatos deben pasar por
    resolve_document (B8) y los validadores (B2) antes de aceptarse.

    Args:
        vlm_result: Resultado del VLM.
        page: Página asociada.

    Returns:
        Lista de Candidate listos para usar en resolve_document.
    """
    from app.application.pipeline.extract_candidates import Candidate as Candidate  # noqa: F811

    candidates: list[Candidate] = []
    for field in vlm_result.fields:
        candidates.append(
            Candidate(
                field_name=field.field_name,
                value=field.value,
                normalized_value=field.value,
                confidence=field.confidence * 0.7,  # Reducir por ser fuente VLM
                block=None,  # El VLM no proporciona bbox de bloque
                page=field.page or page,
            )
        )
    return candidates