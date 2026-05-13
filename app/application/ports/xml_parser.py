"""Puerto para parseo de XML de facturas electrónicas."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.application.ports.xml_extractor import XmlFormat


@dataclass(frozen=True)
class ParsedInvoiceData:
    """Datos extraídos de un XML de factura electrónica."""

    invoice_number: str | None = None
    issue_date: str | None = None  # ISO format string
    due_date: str | None = None

    supplier_name: str | None = None
    supplier_tax_id: str | None = None

    customer_name: str | None = None
    customer_tax_id: str | None = None

    tax_lines: list[dict[str, Any]] | None = None
    # Each dict: {"tax_rate": Decimal, "tax_base": Decimal, "tax_amount": Decimal}

    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None

    advance_amount: Decimal | None = None
    withholding_amount: Decimal | None = None

    raw_xml: bytes | None = None


class XmlParser(ABC):
    """Puerto abstracto para parsear XML de facturas en distintos formatos."""

    @abstractmethod
    def can_parse(self, format: XmlFormat) -> bool:
        """Indica si este parser soporta el formato dado."""

    @abstractmethod
    def parse(self, xml_content: bytes) -> ParsedInvoiceData | None:
        """Parsea el XML y devuelve los datos extraídos.

        Devuelve None si el parseo falla o el XML no corresponde a este parser.
        """