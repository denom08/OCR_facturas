"""Modelos de debug y metadatos operativos para include_debug.

Sigue las restricciones de B12:
- NO contenido de factura completo
- NO archivos o imágenes
- SÍ: request_id, timings, decisiones, PDF kind, engine, candidato count

El campo `InvoiceResponse.debug` recibe uno de estos objetos.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DebugInfo:
    """Metadatos de debug para incluir en InvoiceResponse.

    Nunca incluye contenido de facturas, solo metadatos operativos.
    """

    request_id: str
    stage: str
    timings: dict[str, Any]
    pdf_kind: str | None = None
    pipeline: str | None = None
    engine: str | None = None
    candidate_count: int | None = None
    resolved_fields: list[str] = field(default_factory=list)
    warnings_count: int = 0
    errors_count: int = 0
    vlm_used: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte a dict compatible con InvoiceResponse.debug."""
        result: dict[str, Any] = {
            "request_id": self.request_id,
            "stage": self.stage,
            "timings": self.timings,
        }
        if self.pdf_kind:
            result["pdf_kind"] = self.pdf_kind
        if self.pipeline:
            result["pipeline"] = self.pipeline
        if self.engine:
            result["engine"] = self.engine
        if self.candidate_count is not None:
            result["candidate_count"] = self.candidate_count
        if self.resolved_fields:
            result["resolved_fields"] = self.resolved_fields
        if self.warnings_count:
            result["warnings_count"] = self.warnings_count
        if self.errors_count:
            result["errors_count"] = self.errors_count
        if self.vlm_used:
            result["vlm_used"] = True
        result.update(self.extra)
        return result


def build_debug_info(
    request_id: str,
    stage: str,
    timings: dict[str, Any],
    *,
    pdf_kind: str | None = None,
    pipeline: str | None = None,
    engine: str | None = None,
    candidate_count: int | None = None,
    resolved_fields: list[str] | None = None,
    warnings_count: int = 0,
    errors_count: int = 0,
    vlm_used: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Factory para construir el dict de debug sin duplicar lógica en pipelines.

    Usage:
        debug = build_debug_info(
            request_id=get_request_id(),
            stage="digital_pipeline",
            timings=timing_collector.to_dict(),
            pdf_kind=kind.value,
            pipeline="digital",
            candidate_count=len(candidates.candidates),
            resolved_fields=list(resolved.keys()),
        )
    """
    di = DebugInfo(
        request_id=request_id,
        stage=stage,
        timings=timings,
        pdf_kind=pdf_kind,
        pipeline=pipeline,
        engine=engine,
        candidate_count=candidate_count,
        resolved_fields=resolved_fields or [],
        warnings_count=warnings_count,
        errors_count=errors_count,
        vlm_used=vlm_used,
        extra=extra,
    )
    return di.to_dict()


# -------------------------------------------------------------------
# Nota sobre debug visual (opt-in futuro)
# -------------------------------------------------------------------
# El guardado opcional de imágenes con cajas detectadas (bounding boxes)
# queda como PENDIENTE por restricciones de privacidad y alcance:
#
# - Requeriría guardar imágenes en disco o transmitirlas, lo que afecta privacidad
# - No está en el alcance MVP del proyecto actual
# - Puede implementarse como feature opt-in futura con:
#   1. Banded Pipeline con flag `--save-debug-images` o similar
#   2. Almacenamiento en volumen efímero/tmpfs con TTL corto
#   3. Interfaz de revisión humana (fuera del alcance actual)
#
# Para implementarlo en el futuro:
# - Crear puerto `DebugImageStorage` en app/application/ports/
# - Añadir `save_debug_image(image_data, request_id, page, boxes)` al puerto
# - El endpoint debería recibir `save_debug_images: bool = False`
# - Los pipelines lo reciben como parámetro opcional
# - Documentar en docs/observability.md cuando se implemente

DEBUG_VISUAL_PENDING = True