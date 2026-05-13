"""Ports (interfaces) de la capa de aplicación."""

from app.application.ports.invoice_extractor import (
    InvoiceExtractor as InvoiceExtractor,
)
from app.application.ports.invoice_extractor import (
    VlmExtractedField as VlmExtractedField,
)
from app.application.ports.invoice_extractor import (
    VlmExtractionResult as VlmExtractionResult,
)
from app.application.ports.invoice_extractor import (
    VlmParseError as VlmParseError,
)
from app.application.ports.invoice_extractor import (
    VlmRawResponse as VlmRawResponse,
)
from app.application.ports.invoice_extractor import (
    VlmUnavailableError as VlmUnavailableError,
)
from app.application.ports.pdf_reader import (
    ImageInfo as ImageInfo,
)
from app.application.ports.pdf_reader import (
    PdfKind as PdfKind,
)
from app.application.ports.pdf_reader import (
    PdfReader as PdfReader,
)
from app.application.ports.pdf_reader import (
    TextBlock as TextBlock,
)

__all__ = [
    "PdfReader",
    "PdfKind",
    "TextBlock",
    "ImageInfo",
    "InvoiceExtractor",
    "VlmExtractionResult",
    "VlmExtractedField",
    "VlmUnavailableError",
    "VlmParseError",
    "VlmRawResponse",
]