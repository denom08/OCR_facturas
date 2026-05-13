"""Ports (interfaces) de la capa de aplicación."""

from app.application.ports.pdf_reader import (
    ImageInfo,
    PdfKind,
    PdfReader,
    TextBlock,
)

__all__ = ["PdfReader", "PdfKind", "TextBlock", "ImageInfo"]