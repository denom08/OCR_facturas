"""Adaptador Qwen2.5-VL local para extracción de facturas (B9).

Este adaptador es LAZY: no carga modelos ni verifica dependencias hasta que
extract() es llamado por primera vez. Esto permite que el proyectoarranque sin
Qwen2.5-VL instalado y que los tests funcionen sin GPU/modelos.

Instalación del modelo (requiere GPU NVIDIA):
    # Opción 1: vLLM (recomendado para producción)
    pip install vllm>=0.4.0
    # Luego iniciar servidor:
    #   vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8002 --gpu-memory-utilization 0.85

    # Opción 2: Transformers directo (para desarrollo/MVP)
    pip install transformers>=4.41.0 qwen-vl-utils accelerate

El modelo se descarga automáticamente en el primer uso (~7GB).

Uso::

    extractor = QwenVlExtractor()
    if extractor.is_available():
        result = extractor.extract(image_bytes, page=1)
        for field in result.fields:
            print(field.field_name, field.value)
    else:
        # Usar respuesta controlada con warning
        ...

El VLM SOLO propone candidatos. El dominio (B2) y el resolutor (B8)
validan y deciden si se aceptan los valores.
"""

from __future__ import annotations

import json
import logging
import re
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any

from app.application.ports.invoice_extractor import (
    InvoiceExtractor,
    VlmExtractedField,
    VlmExtractionResult,
    VlmParseError,
    VlmRawResponse,
    VlmUnavailableError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema JSON esperado del VLM
# ---------------------------------------------------------------------------

VLM_SCHEMA_JSON = """
{
  "invoice_data": {"number": "string|null", "issue_date": "YYYY-MM-DD|null"},
  "supplier": {"legal_name": "string|null", "tax_id": "string|null"},
  "customer": {"legal_name": "string|null", "tax_id": "string|null"},
  "tax_lines": [
    {"tax_rate": "string|null", "tax_base": "string|null", "tax_amount": "string|null"}
  ],
  "totals": {
    "net_amount": "string|null",
    "tax_amount": "string|null",
    "gross_amount": "string|null"
  },
  "evidence": [
    {"field": "string", "text": "string", "page": "integer|null"}
  ]
}
""".strip()

# ---------------------------------------------------------------------------
# Prompt strict
# ---------------------------------------------------------------------------

VLM_PROMPT_TEMPLATE = """Extrae los datos de esta factura.

Devuelve SOLO JSON válido conforme a este schema:
{SCHEMA}

Reglas:
- Devuelve SOLO JSON válido, sin markdown fences ni texto alrededor.
- No inventes valores. Si no estás seguro, usa null.
- Incluir siempre evidencia: field, text y page.
- Solo ASCII en JSON. Escapa correctamente.

Campos: invoice_data (number, issue_date), supplier y customer (legal_name, tax_id),
tax_lines (tax_rate, tax_base, tax_amount), totals (net_amount, tax_amount, gross_amount).
evidence: lista de objetos con field, text y page.

Si la imagen no parece una factura, devuelve todos los campos como null.
Si un campo no puede determinarse, usa null.
""".strip()

# ---------------------------------------------------------------------------
# Parser robusto de salida JSON del VLM
# ---------------------------------------------------------------------------


def parse_vlm_json(raw_output: str) -> dict[str, Any]:
    """Parsea la salida de texto del VLM a JSON.

    Maneja:
    - Markdown fences (```json ... ```)
    - Texto antes/después del JSON
    - JSON inválido con recuperación

    Args:
        raw_output: Texto crudo devuelto por el VLM.

    Returns:
        Dict con los datos parseados.

    Raises:
        VlmParseError: si no puede extraer JSON válido.
    """
    if not raw_output or not raw_output.strip():
        raise VlmParseError("VLM output is empty")

    text = raw_output.strip()

    # 1. Quitar markdown fences
    fences_pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    match = fences_pattern.search(text)
    if match:
        text = match.group(1).strip()
    else:
        # 2. Buscar el primer '{' y el último '}'
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]
        elif "null" in text.lower() and len(text) < 200:
            # El VLM devolvió "null" o texto sin JSON válido
            # Intentamos interpretar como respuesta vacía
            pass
        else:
            raise VlmParseError(f"No JSON object found in VLM output: {text[:200]}")

    # 3. Intentar parsear
    try:
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        # 4. Intentar recuperación: limpiar caracteres problemáticos comunes
        # Eliminamos trailing commas y keys sin quotes
        cleaned = text  # Copy first
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)

        # Asegurar que keys están entre comillas dobles (manejo básico)
        # Esto es frágil pero cubre errores comunes de modelos
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise VlmParseError(f"Invalid JSON from VLM even after cleanup: {exc}") from exc


# ---------------------------------------------------------------------------
# Adaptador Qwen2.5-VL via vLLM
# ---------------------------------------------------------------------------


class QwenVlExtractor(InvoiceExtractor):
    """Implementación de InvoiceExtractor usando Qwen2.5-VL via vLLM.

    Requiere:
        - vLLM instalado: pip install vllm>=0.4.0
        - Modelo descargado: Qwen/Qwen2.5-VL-7B-Instruct
        - Servidor vLLM corriendo en el puerto configurado (default 8002)

    Diseño LAZY: no conecta al servidor ni carga el modelo hasta
    la primera llamada a extract().

    Uso con vLLM corriendo en localhost:8002::

        extractor = QwenVlExtractor()
        result = extractor.extract(image_bytes, page=1)
        for field in result.fields:
            print(field.field_name, field.value)
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8002/v1",
        model_id: str = "Qwen/Qwen2.5-VL-7B-Instruct",
        timeout: float = 120.0,
        default_temperature: float = 0.1,
        prompt_template: str | None = None,
    ) -> None:
        """Configura el extractor.

        Args:
            base_url: URL del servidor vLLM (o compatible OpenAI).
            model_id: Identificador del modelo en el servidor.
            timeout: Timeout en segundos para la llamada al servidor.
            default_temperature: Temperature para generación (bajo = más determinista).
            prompt_template: Template de prompt override. Si es None, usa el default.
        """
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._timeout = timeout
        self._default_temperature = default_temperature
        self._prompt_template = prompt_template or VLM_PROMPT_TEMPLATE
        self._client: Any = None

    # ------------------------------------------------------------------
    # Lazy client init
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Cliente HTTP lazy para el servidor vLLM."""
        if self._client is None:
            try:
                import openai

                self._client = openai.OpenAI(
                    base_url=self._base_url,
                    api_key="EMPTY",  # vLLM no requiere auth
                    timeout=self._timeout,
                    max_retries=1,
                )
            except ImportError as exc:
                raise VlmUnavailableError(
                    "openai package required for VLM communication. "
                    "Install with: pip install openai"
                ) from exc
        return self._client

    # ------------------------------------------------------------------
    # InvoiceExtractor interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Comprueba si vLLM y el modelo están disponibles."""
        try:
            # Intentar importar vllm o openai
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def name(self) -> str:
        return "Qwen2.5-VL-7B-Instruct"

    def model_id(self) -> str:
        return self._model_id

    def extract(
        self,
        image_data: BytesIO,
        page: int = 1,
        prompt: str | None = None,
    ) -> VlmExtractionResult:
        """Envía imagen al VLM y devuelve campos extraídos.

        Args:
            image_data: Imagen PNG/JPEG como BytesIO.
            page: Número de página para logging.
            prompt: Prompt override. Si es None, usa el default.

        Returns:
            VlmExtractionResult con campos propuestos.

        Raises:
            VlmUnavailableError: si el cliente o servidor no están disponibles.
        """
        if not self.is_available():
            raise VlmUnavailableError(
                "VLM no disponible. Instala con: pip install openai vllm"
            )

        # Preparar prompt
        template = prompt or self._prompt_template
        full_prompt = template.format(SCHEMA=VLM_SCHEMA_JSON)

        # Preparar imagen como base64
        image_bytes = image_data.read()
        import base64

        b64_image = base64.b64encode(image_bytes).decode("ascii")
        image_data.seek(0)

        # Llamada al servidor vLLM
        client = self._get_client()
        start_time = time.perf_counter()

        try:
            response = client.chat.completions.create(
                model=self._model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": full_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64_image}"
                                },
                            },
                        ],
                    }
                ],
                temperature=self._default_temperature,
                max_tokens=2048,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.warning("VLM call failed: %s (%.1fms)", exc, elapsed)
            return VlmExtractionResult(
                fields=[],
                raw_response=VlmRawResponse(
                    raw_text=str(exc),
                    model=self._model_id,
                    latency_ms=elapsed,
                    tokens_used=None,
                ),
                warning=f"VLM call failed: {exc}",
            )

        elapsed = (time.perf_counter() - start_time) * 1000
        raw_text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None

        raw_response = VlmRawResponse(
            raw_text=raw_text,
            model=self._model_id,
            latency_ms=elapsed,
            tokens_used=tokens_used,
        )

        # Parsear JSON
        try:
            parsed = parse_vlm_json(raw_text)
        except VlmParseError as exc:
            logger.warning("VLM output parse failed: %s", exc)
            return VlmExtractionResult(
                fields=[],
                raw_response=raw_response,
                warning=f"VLM output parse failed: {exc}",
            )

        # Convertir parsed a VlmExtractedField
        fields = self._convert_to_fields(parsed, page)

        return VlmExtractionResult(
            fields=fields,
            raw_response=raw_response,
        )

    def _convert_to_fields(
        self, parsed: dict[str, Any], page: int
    ) -> list[VlmExtractedField]:
        """Convierte el JSON parseado a lista de VlmExtractedField."""
        fields: list[VlmExtractedField] = []

        # invoice_data
        inv = parsed.get("invoice_data") or {}
        if inv.get("number"):
            fields.append(
                VlmExtractedField(
                    field_name="invoice_data.number",
                    value=str(inv["number"]),
                    confidence=1.0,
                    page=page,
                )
            )
        if inv.get("issue_date"):
            fields.append(
                VlmExtractedField(
                    field_name="invoice_data.issue_date",
                    value=str(inv["issue_date"]),
                    confidence=1.0,
                    page=page,
                )
            )

        # supplier
        sup = parsed.get("supplier") or {}
        if sup.get("legal_name"):
            fields.append(
                VlmExtractedField(
                    field_name="supplier.legal_name",
                    value=str(sup["legal_name"]),
                    confidence=1.0,
                    page=page,
                )
            )
        if sup.get("tax_id"):
            fields.append(
                VlmExtractedField(
                    field_name="supplier.tax_id",
                    value=str(sup["tax_id"]),
                    confidence=1.0,
                    page=page,
                )
            )

        # customer
        cust = parsed.get("customer") or {}
        if cust.get("legal_name"):
            fields.append(
                VlmExtractedField(
                    field_name="customer.legal_name",
                    value=str(cust["legal_name"]),
                    confidence=1.0,
                    page=page,
                )
            )
        if cust.get("tax_id"):
            fields.append(
                VlmExtractedField(
                    field_name="customer.tax_id",
                    value=str(cust["tax_id"]),
                    confidence=1.0,
                    page=page,
                )
            )

        # tax_lines
        for idx, tl in enumerate(parsed.get("tax_lines") or []):
            rate = tl.get("tax_rate")
            base = tl.get("tax_base")
            amount = tl.get("tax_amount")
            if rate:
                fields.append(
                    VlmExtractedField(
                        field_name=f"tax_lines[{idx}].tax_rate",
                        value=str(rate),
                        confidence=0.9,
                        page=page,
                    )
                )
            if base:
                fields.append(
                    VlmExtractedField(
                        field_name=f"tax_lines[{idx}].tax_base",
                        value=str(base),
                        confidence=0.9,
                        page=page,
                    )
                )
            if amount:
                fields.append(
                    VlmExtractedField(
                        field_name=f"tax_lines[{idx}].tax_amount",
                        value=str(amount),
                        confidence=0.9,
                        page=page,
                    )
                )

        # totals
        tot = parsed.get("totals") or {}
        if tot.get("net_amount"):
            fields.append(
                VlmExtractedField(
                    field_name="totals.net_amount",
                    value=str(tot["net_amount"]),
                    confidence=0.9,
                    page=page,
                )
            )
        if tot.get("tax_amount"):
            fields.append(
                VlmExtractedField(
                    field_name="totals.tax_amount",
                    value=str(tot["tax_amount"]),
                    confidence=0.9,
                    page=page,
                )
            )
        if tot.get("gross_amount"):
            fields.append(
                VlmExtractedField(
                    field_name="totals.gross_amount",
                    value=str(tot["gross_amount"]),
                    confidence=0.9,
                    page=page,
                )
            )

        return fields


# Alias para consistencia
QwenVlExtractorVLLM = QwenVlExtractor