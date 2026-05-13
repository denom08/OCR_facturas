"""Infraestructura OCR — adaptadores de motores OCR."""

from app.application.ports.ocr_engine import (
    OcrBlock,
    OcrEngine,
    OcrResult,
    OcrUnavailableError,
)
from app.infrastructure.ocr.paddle_ocr_engine import PaddleOcrEngine

__all__ = [
    "OcrBlock",
    "OcrEngine",
    "OcrResult",
    "OcrUnavailableError",
    "PaddleOcrEngine",
]