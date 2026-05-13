"""Motor VLM fake para tests sin dependencia de Qwen/vLLM."""

from io import BytesIO

from app.application.ports.invoice_extractor import (
    InvoiceExtractor,
    VlmExtractedField,
    VlmExtractionResult,
    VlmRawResponse,
)


class FakeVlmExtractor(InvoiceExtractor):
    """Extractor VLM falso para tests.

    Devuelve campos preconfigurados con confidences controladas.
    Útil para tests de integración y unitarios sin instalar Qwen/vLLM.

    Uso::

        extractor = FakeVlmExtractor(fields=[...])
        assert extractor.is_available() == True
        result = extractor.extract(some_image)
        assert len(result.fields) == 2
    """

    def __init__(
        self,
        fields: list[VlmExtractedField] | None = None,
        available: bool = True,
        name: str = "FakeVLM",
        model_id: str = "fake/fake-vlm-7b",
        warning: str | None = None,
    ) -> None:
        """Configura el extractor fake.

        Args:
            fields: Lista de VlmExtractedField a devolver. Si es None,
                devuelve campos de ejemplo.
            available: Valor a devolver por is_available().
            name: Nombre del extractor para debug.
            model_id: Identificador del modelo fake.
            warning: Warning a incluir en el resultado (opcional).
        """
        self._fields = fields or [
            VlmExtractedField(
                field_name="invoice_data.number",
                value="2024/001",
                confidence=1.0,
                page=1,
            ),
            VlmExtractedField(
                field_name="invoice_data.issue_date",
                value="2024-01-15",
                confidence=1.0,
                page=1,
            ),
            VlmExtractedField(
                field_name="supplier.legal_name",
                value="Empresa Fake S.L.",
                confidence=0.95,
                page=1,
            ),
            VlmExtractedField(
                field_name="supplier.tax_id",
                value="B12345678",
                confidence=0.95,
                page=1,
            ),
        ]
        self._available = available
        self._name = name
        self._model_id = model_id
        self._warning = warning

    def is_available(self) -> bool:
        return self._available

    def name(self) -> str:
        return self._name

    def model_id(self) -> str:
        return self._model_id

    def extract(
        self, image_data: BytesIO, page: int = 1, prompt: str | None = None
    ) -> VlmExtractionResult:
        return VlmExtractionResult(
            fields=[f for f in self._fields],
            raw_response=VlmRawResponse(
                raw_text='{"invoice_data": {"number": "2024/001"}}',
                model=self._model_id,
                latency_ms=50.0,
                tokens_used=100,
            ),
            warning=self._warning,
        )


class UnavailableVlmExtractor(InvoiceExtractor):
    """Extractor VLM que siempre responde que no está disponible.

    Útil para probar el comportamiento controlado cuando falta el VLM.
    """

    def is_available(self) -> bool:
        return False

    def name(self) -> str:
        return "UnavailableVLM"

    def model_id(self) -> str:
        return "n/a"

    def extract(
        self, image_data: BytesIO, page: int = 1, prompt: str | None = None
    ) -> VlmExtractionResult:
        raise AssertionError(
            "UnavailableVlmExtractor.extract no debería ser llamado"
        )