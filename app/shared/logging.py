"""Logging estructurado por request con request_id y timings.

Diseñado para observabilidad sin persistir datos sensibles:
- request_id generado por request
- timings por etapa del pipeline
- logs estructurados en JSON para consumo externo
- SIN datos de facturas en logs
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Context variable para request_id — thread-safe para async
_request_id_var: ContextVar[str] = ContextVar("request_id", default="no-request-id")

# Logger de la aplicación
_logger = logging.getLogger("app")


def get_request_id() -> str:
    """Obtiene el request_id del contexto actual."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Establece el request_id en el contexto."""
    _request_id_var.set(request_id)


def generate_request_id() -> str:
    """Genera un nuevo request_id únicos."""
    return str(uuid.uuid4())


# -------------------------------------------------------------------
# Estructura de timing por etapa
# -------------------------------------------------------------------


@dataclass
class StageTiming:
    """Tiempo medido para una etapa del pipeline."""

    stage: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class TimingCollector:
    """Recoge timings de cada etapa del pipeline."""

    __slots__ = ("_stages", "_start_time")

    def __init__(self) -> None:
        self._stages: list[StageTiming] = []
        self._start_time: float | None = None

    def start(self) -> None:
        """Marca el inicio del procesamiento."""
        self._start_time = _time_ms()

    def add_stage(self, stage: str, duration_ms: float, **metadata: Any) -> None:
        """Registra una etapa completada."""
        self._stages.append(
            StageTiming(stage=stage, duration_ms=duration_ms, metadata=metadata)
        )

    def get_stages(self) -> list[StageTiming]:
        """Devuelve todas las etapas registradas."""
        return list(self._stages)

    def total_ms(self) -> float:
        """Tiempo total desde start() hasta ahora."""
        if self._start_time is None:
            return 0.0
        return _time_ms() - self._start_time

    def to_dict(self) -> dict[str, Any]:
        """Convierte a dict para incluir en debug."""
        return {
            "total_ms": round(self.total_ms(), 2),
            "stages": [
                {
                    "stage": s.stage,
                    "duration_ms": round(s.duration_ms, 2),
                    **s.metadata,
                }
                for s in self._stages
            ],
        }


def _time_ms() -> float:
    """Tiempo actual en milisegundos."""
    return time.perf_counter() * 1000


# -------------------------------------------------------------------
# Helper: context manager para timing de etapa
# -------------------------------------------------------------------


class stage_timer:
    """Context manager para medir tiempo de una etapa.

    Usage:
        timing = TimingCollector()
        timing.start()
        with stage_timer(timing, "pdf_classify"):
            # hacer algo
        debug = {"timings": timing.to_dict()}
    """

    def __init__(
        self, collector: TimingCollector, stage: str, **metadata: Any
    ) -> None:
        self._collector = collector
        self._stage = stage
        self._metadata = metadata
        self._start: float | None = None

    def __enter__(self) -> "stage_timer":
        self._start = _time_ms()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._start is not None:
            duration = _time_ms() - self._start
            self._collector.add_stage(self._stage, duration, **self._metadata)


# -------------------------------------------------------------------
# Logging estructurado
# -------------------------------------------------------------------


def _log(level: int, event: str, **data: Any) -> None:
    """Log estructurado en JSON sin datos sensibles de facturas."""
    request_id = get_request_id()
    entry = {
        "event": event,
        "request_id": request_id,
        **data,
    }
    _logger.log(level, json.dumps(entry))


def log_info(event: str, **data: Any) -> None:
    """Log INFO sin datos sensibles."""
    _log(logging.INFO, event, **data)


def log_warning(event: str, **data: Any) -> None:
    """Log WARNING sin datos sensibles."""
    _log(logging.WARNING, event, **data)


def log_error(event: str, **data: Any) -> None:
    """Log ERROR sin datos sensibles."""
    _log(logging.ERROR, event, **data)


def log_debug(event: str, **data: Any) -> None:
    """Log DEBUG sin datos sensibles."""
    _log(logging.DEBUG, event, **data)


# -------------------------------------------------------------------
# Configuración del logging
# -------------------------------------------------------------------

LOG_FORMAT_JSON = "json"
LOG_FORMAT_TEXT = "text"
LOG_FORMAT_AUTO = "auto"


def configure_logging(
    level: str = "INFO",
    format: str = LOG_FORMAT_AUTO,
) -> None:
    """Configura el logging de la aplicación.

    Args:
        level: Nivel de log (DEBUG, INFO, WARNING, ERROR).
        format: Formato (json, text, auto). Auto usa JSON en producción.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if format == LOG_FORMAT_JSON or (format == LOG_FORMAT_AUTO and log_level < logging.INFO):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.basicConfig(
            level=log_level,
            handlers=[handler],
        )
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )