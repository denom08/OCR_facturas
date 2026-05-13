"""Motor OCR fake para tests sin dependencia de PaddleOCR."""

from io import BytesIO

from app.application.ports.ocr_engine import OcrBlock, OcrEngine, OcrResult


class FakeOcrEngine(OcrEngine):
    """Motor OCR falso para tests.

    Devuelve texto preconfigurado con bloques y confidences controladas.
    Útil para tests de integración y unitarios sin instalar PaddleOCR.

    Uso::

        engine = FakeOcrEngine()
        assert engine.is_available() == True  # siempre disponible para tests
        result = engine.process_image(some_image)
        assert len(result.blocks) == 2
    """

    def __init__(
        self,
        blocks: list[OcrBlock] | None = None,
        available: bool = True,
        name: str = "FakeOCR",
    ) -> None:
        """Configura el motor fake.

        Args:
            blocks: Lista de OcrBlock a devolver en cada page. Si es None,
                devuelve un bloque genérico.
            available: Valor a devolver por is_available().
            name: Nombre del motor para debug.
        """
        self._blocks = [
            OcrBlock(
                text="FACTURAejemplo",
                bbox=(50.0, 100.0, 200.0, 130.0),
                confidence=0.95,
            ),
        ] if blocks is None else blocks
        self._available = available
        self._name = name

    def is_available(self) -> bool:
        return self._available

    def name(self) -> str:
        return self._name

    def process_image(self, image_data: BytesIO, page: int = 1) -> OcrResult:
        return OcrResult(
            blocks=[blk for blk in self._blocks],
            page=page,
            engine=self._name,
        )


class UnavailableOcrEngine(OcrEngine):
    """Motor OCR que siempre responde que no está disponible.

    Útil para probar el comportamiento controlado cuando falta OCR.
    """

    def is_available(self) -> bool:
        return False

    def name(self) -> str:
        return "UnavailableOCR"

    def process_image(self, image_data: BytesIO, page: int = 1) -> OcrResult:
        raise AssertionError(
            "UnavailableOcrEngine.process_image no debería ser llamado"
        )