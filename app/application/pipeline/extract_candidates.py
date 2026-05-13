"""Extracción de candidatos por patrones para PDFs digitales.

Produce candidatos para cada campo buscándolos mediante regex y heuristics.
Los candidatos se envían después a los validadores de dominio y al resolutor de campos.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.application.pipeline.normalize_document import (
    NormalizedBlock,
    NormalizedDocument,
)
from app.shared.money import normalize_money

# -------------------------------------------------------------------
# Patrones compilados
# -------------------------------------------------------------------

# CIF/NIF/NIE: letras permitidas, 8 dígitos + 1 letra o bien variante NIE
_CIF_NIF_NIE_PATTERN = re.compile(
    r"\b([ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J])\b"
    r"|"
    r"\b(\d{8}[A-Z])\b"
    r"|"
    r"\b([XYZ]\d{7}[A-Z])\b"
)
# NIF con guiones visuales tipo "12345678-A"
_NIF_VISUAL_PATTERN = re.compile(r"\b(\d{8})-([A-Z])\b")

# Fecha de factura: múltiples formatos
_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"),
    re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"),
]
# Palabras clave asociadas a fechas
_DATE_KEYWORDS = re.compile(
    r"(?i)\b(fecha\s*(de)?\s*(factura|emisión|expedición|emision)?)"
    r"|\b(f\.? ?em\.?)\b"
    r"|\b(issue\s*date)\b",
    re.IGNORECASE,
)

# Número de factura: busca patrones de número de factura comunes en texto de factura
_INVOICE_NUMBER_PATTERN = re.compile(
    r"(?i)\b(\d{2,4}[/\-]\d{3,6})\b"  # YYYY/NNNN, YYYY-NNNN
    r"|"
    r"\b(F\s*[/\-]?\s*\d{3,6})\b"  # F/123456, F-123456
    r"|"
    r"\b([A-Z]?\d{2,4}[/\-]\d{3,6})\b"  # 24/0001 style
)

# Entidades legales
_EMISOR_KEYWORDS = re.compile(
    r"(?i)\b(emitid[oa]|emisor|proveedor|vendedor|vendor|"
    r"de\s+parte\s+de|"
    r"ship\s*from|"
    r"supplier|seller)\b",
    re.IGNORECASE,
)
_CLIENTE_KEYWORDS = re.compile(
    r"(?i)\b(domicilio\s+(de\s+)?(entrega|cliente|destino)|"
    r"cliente|comprador|buyer|customer|purchaser|"
    r"bill\s*to|ship\s*to|billed\s*to)\b",
    re.IGNORECASE,
)

# Razón social (heurística: líneas que parecen nombres de empresa)
_COMPANY_NAME_PATTERN = re.compile(
    r"(?i)\b(S\.?L\.?|S\.?A\.?|S\.?L\.?U\.?|S\.?A\.?U\.?|"
    r"limitada|anónima|anónima|"
    r"bis断续|sl|sa|slu|sau)\b"
)

# Base imponible
_TAX_BASE_PATTERNS = re.compile(
    r"(?i)\b(base\s+(imponible)?|base\s+tax|taxable\s+base|imponible)\b"
)
_TAX_BASE_AMOUNT = re.compile(
    r"(?i)(?:base\s+(imponible)?\s*[:;]?\s*)([0-9.,]+\s*€?|EUR\s*[0-9.,]+)"
)

# IVA / impuesto
_IVA_PATTERNS = re.compile(
    r"(?i)\b(iva|impuesto|tax|vat|i\.?v\.?a\.?)\b"
)
_IVA_LINE_PATTERN = re.compile(
    r"(?i)(?:(?:tipo\s+)?iva|impuesto|tax|vat)\s*"
    r"(\d{1,2}[.,]?\d{0,2})\s*%?\s*[:]?\s*"
    r"([0-9]+[.,]\d{2})\s*(?:€|eur|EUR)?"
)
_IVA_PCT_PATTERN = re.compile(r"(\d{1,2}[.,]\d{0,2})\s*%?")

# Total factura
_TOTAL_PATTERNS = re.compile(
    r"(?i)\b(total\s+(factura|general|bruto)|"
    r"importe\s+total|"
    r"total\s+(a\s+)?pagar|"
    r"grand\s+total|"
    r"amount\s+due|"
    r"total\s*[=:]\s*[0-9.,]+\s*€?)\b"
)
_TOTAL_AMOUNT_PATTERN = re.compile(
    r"(?i)(?:total\s+(factura|general|bruto|importe)?\s*[:]?\s*)"
    r"([0-9.,]+\s*€?|EUR\s*[0-9.,]+)"
)

# Símbolos monetarios
_EUR_PATTERN = re.compile(
    r"([0-9]{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|eur|EUR)",
    re.IGNORECASE,
)


# -------------------------------------------------------------------
# Candidates
# -------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """Un candidato para un campo extraído."""

    field_name: str  # e.g. "invoice_data.number", "supplier.tax_id"
    value: str
    normalized_value: str | None = None
    confidence: float = 0.5
    block: NormalizedBlock | None = None
    page: int = 1


@dataclass
class CandidateSet:
    """Conjunto de candidatos para un documento."""

    candidates: list[Candidate] = field(default_factory=list)

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)

    def by_field(self, field_name: str) -> list[Candidate]:
        return [c for c in self.candidates if c.field_name == field_name]

    def best_for(self, field_name: str) -> Candidate | None:
        """El candidato con mayor confidence para un campo."""
        matching = sorted(
            self.by_field(field_name), key=lambda c: c.confidence, reverse=True
        )
        return matching[0] if matching else None


# -------------------------------------------------------------------
# Normalización de valores
# -------------------------------------------------------------------


def _normalize_tax_id(raw: str) -> str:
    return re.sub(r"[\s\-.]", "", raw.upper())


def _normalize_money_text(raw: str) -> Decimal | None:
    try:
        return normalize_money(raw)
    except ValueError:
        return None


# -------------------------------------------------------------------
# Extracción de candidatos
# -------------------------------------------------------------------


def extract_candidates(doc: NormalizedDocument) -> CandidateSet:
    """Extrae candidatos de todos los campos desde el documento normalizado."""

    cs = CandidateSet()
    all_blocks = doc.all_blocks

    _extract_invoice_number(cs, all_blocks)
    _extract_dates(cs, all_blocks)
    _extract_supplier_tax_id(cs, all_blocks)
    _extract_customer_tax_id(cs, all_blocks)
    _extract_company_names(cs, all_blocks)
    _extract_tax_lines(cs, all_blocks)
    _extract_totals(cs, all_blocks)

    return cs


def _extract_invoice_number(cs: CandidateSet, blocks: list[NormalizedBlock]) -> None:
    """Extrae el número de factura."""
    for block in blocks:
        text = block.text
        match = _INVOICE_NUMBER_PATTERN.search(text)
        if match:
            raw_number = match.group(1)
            cs.add(
                Candidate(
                    field_name="invoice_data.number",
                    value=raw_number.strip(),
                    confidence=0.85,
                    block=block,
                    page=block.page,
                )
            )
            return


def _extract_dates(cs: CandidateSet, blocks: list[NormalizedBlock]) -> None:
    """Extrae la fecha de factura."""
    for block in blocks:
        text = block.text
        if not _DATE_KEYWORDS.search(text):
            continue

        for date_pat in _DATE_PATTERNS:
            match = date_pat.search(text)
            if match:
                g = match.groups()
                try:
                    if len(g[2]) == 4:  # group 3 is 4-digit year → YYYY-MM-DD
                        raw = f"{g[0]}-{g[1]}-{g[2]}"
                    else:  # group 1 is day → DD-MM-YYYY
                        raw = f"{g[0]}-{g[1]}-{g[2]}"
                    cs.add(
                        Candidate(
                            field_name="invoice_data.issue_date",
                            value=raw,
                            confidence=0.85,
                            block=block,
                            page=block.page,
                        )
                    )
                    return
                except Exception:
                    continue


def _extract_supplier_tax_id(
    cs: CandidateSet, blocks: list[NormalizedBlock]
) -> None:
    """Extrae el CIF/NIF/NIE del emisor."""
    for block in blocks:
        text = block.text
        # Una vez que vemos EMISOR/proveedor, capturar el primer CIF del bloque
        if _EMISOR_KEYWORDS.search(text):
            for match in _CIF_NIF_NIE_PATTERN.finditer(text):
                tax_id = _normalize_tax_id(match.group())
                cs.add(
                    Candidate(
                        field_name="supplier.tax_id",
                        value=tax_id,
                        normalized_value=tax_id,
                        confidence=0.85,
                        block=block,
                        page=block.page,
                    )
                )
                return  # Primer CIF del bloque tras la palabra EMISOR

            for match in _NIF_VISUAL_PATTERN.finditer(text):
                tax_id = match.group(1) + match.group(2)
                cs.add(
                    Candidate(
                        field_name="supplier.tax_id",
                        value=tax_id,
                        normalized_value=_normalize_tax_id(tax_id),
                        confidence=0.8,
                        block=block,
                        page=block.page,
                    )
                )
                return


def _extract_customer_tax_id(
    cs: CandidateSet, blocks: list[NormalizedBlock]
) -> None:
    """Extrae el CIF/NIF/NIE del cliente."""
    for block in blocks:
        text = block.text
        if _CLIENTE_KEYWORDS.search(text):
            # Tomar el primer CIF que aparezca DESPUÉS de la palabra CLIENTE
            cliente_pos = _CLIENTE_KEYWORDS.search(text).start()
            for match in _CIF_NIF_NIE_PATTERN.finditer(text):
                if match.start() > cliente_pos:
                    tax_id = _normalize_tax_id(match.group())
                    cs.add(
                        Candidate(
                            field_name="customer.tax_id",
                            value=tax_id,
                            normalized_value=tax_id,
                            confidence=0.85,
                            block=block,
                            page=block.page,
                        )
                    )
                    return

            for match in _NIF_VISUAL_PATTERN.finditer(text):
                if match.start() > cliente_pos:
                    tax_id = match.group(1) + match.group(2)
                    cs.add(
                        Candidate(
                            field_name="customer.tax_id",
                            value=tax_id,
                            normalized_value=_normalize_tax_id(tax_id),
                            confidence=0.8,
                            block=block,
                            page=block.page,
                        )
                    )
                    return


def _extract_company_names(cs: CandidateSet, blocks: list[NormalizedBlock]) -> None:
    """Extrae razones sociales para emisor y cliente."""

    supplier_candidates: list[tuple[str, float, NormalizedBlock]] = []
    customer_candidates: list[tuple[str, float, NormalizedBlock]] = []

    for block in blocks:
        text = block.text

        if _EMISOR_KEYWORDS.search(text):
            section = "supplier"
        elif _CLIENTE_KEYWORDS.search(text):
            section = "customer"
        elif _COMPANY_NAME_PATTERN.search(text):
            # La línea contiene un patrón de tipo social (S.L., S.A., etc.)
            # La capturamos como posible nombre
            line = text.strip()
            if line and 5 <= len(line) <= 80:
                if section == "supplier":
                    supplier_candidates.append((line, 0.85, block))
                elif section == "customer":
                    customer_candidates.append((line, 0.85, block))
        else:
            #掉的fallback: líneas que parecen nombres de empresa
            # (evitar líneas con importes, palabras clave de factura)
            line = text.strip()
            price_indicators = re.compile(
                r"(?i)\d+[.,]\d+\s*(€|eur)|"  # importes
                r"\b(base|iva|total|factura|importe|tax|amount)\b|"  # palabras de factura
                r"^\d"  # líneas que empiezan por número
            )
            if (
                line
                and 5 <= len(line) <= 80
                and not line.isdigit()
                and not price_indicators.search(line)
                and re.match(r"^[A-ZÁÉÍÓÚÑ]", line)
            ):
                if section == "supplier":
                    supplier_candidates.append((line, 0.6, block))
                elif section == "customer":
                    customer_candidates.append((line, 0.6, block))

    for name, conf, block in supplier_candidates[:2]:
        cs.add(
            Candidate(
                field_name="supplier.legal_name",
                value=name,
                confidence=conf,
                block=block,
                page=block.page,
            )
        )

    for name, conf, block in customer_candidates[:2]:
        cs.add(
            Candidate(
                field_name="customer.legal_name",
                value=name,
                confidence=conf,
                block=block,
                page=block.page,
            )
        )


def _extract_tax_lines(cs: CandidateSet, blocks: list[NormalizedBlock]) -> None:
    """Extrae líneas de IVA: base imponible e importe de IVA por tipo de IVA."""

    iva_rates: dict[str, tuple[float, NormalizedBlock]] = {}
    iva_amounts: dict[str, list[tuple[Decimal, NormalizedBlock]]] = {}
    tax_bases: dict[str, list[tuple[Decimal, NormalizedBlock]]] = {}

    for block in blocks:
        text = block.text

        # Buscar tasas de IVA en formato "IVA 21%: 42,00 EUR"
        if _IVA_PATTERNS.search(text):
            for match in _IVA_LINE_PATTERN.finditer(text):
                raw_rate = match.group(1).replace(",", ".")
                rate_val = float(raw_rate.rstrip("%").strip())
                if 1 <= rate_val <= 27:
                    if rate_val not in iva_rates:
                        iva_rates[rate_val] = (rate_val, block)

                    raw_amount = match.group(2).replace(",", ".")
                    amount = _normalize_money_text(raw_amount)
                    if amount is not None:
                        key = str(rate_val)
                        if key not in iva_amounts:
                            iva_amounts[key] = []
                        iva_amounts[key].append((amount, block))

        # Buscar bases imponibles
        if _TAX_BASE_PATTERNS.search(text):
            for match in _TAX_BASE_AMOUNT.finditer(text):
                raw = (
                    match.group(2)
                    if match.lastindex and match.lastindex >= 2
                    else match.group(1)
                )
                base = _normalize_money_text(raw)
                if base is not None:
                    for rate_val in iva_rates:
                        key = str(rate_val)
                        if key not in tax_bases:
                            tax_bases[key] = []
                        tax_bases[key].append((base, block))

    # Emitir candidatos TaxLine por cada IVA encontrado
    for rate_val, (_rate_norm, block) in iva_rates.items():
        key = str(rate_val)
        bases = tax_bases.get(key, [])
        amounts = iva_amounts.get(key, [])

        if amounts:
            best_amount, _ = max(amounts, key=lambda x: len(amounts))
            cs.add(
                Candidate(
                    field_name=f"tax_lines[{key}].tax_rate",
                    value=str(rate_val),
                    confidence=0.8,
                    block=block,
                    page=block.page,
                )
            )
            if bases:
                best_base, _ = max(bases, key=lambda x: len(bases))
                cs.add(
                    Candidate(
                        field_name=f"tax_lines[{key}].tax_base",
                        value=str(best_base),
                        confidence=0.8,
                        block=block,
                        page=block.page,
                    )
                )
            cs.add(
                Candidate(
                    field_name=f"tax_lines[{key}].tax_amount",
                    value=str(best_amount),
                    confidence=0.8,
                    block=block,
                    page=block.page,
                )
            )


def _extract_totals(cs: CandidateSet, blocks: list[NormalizedBlock]) -> None:
    """Extrae totales: base imponible total, IVA total, total factura."""

    found_net = False
    found_tax = False

    for block in blocks:
        text = block.text

        if _TAX_BASE_PATTERNS.search(text):
            for match in _TAX_BASE_AMOUNT.finditer(text):
                raw = (
                    match.group(2)
                    if match.lastindex and match.lastindex >= 2
                    else match.group(1)
                )
                amount = _normalize_money_text(raw)
                if amount is not None and not found_net:
                    cs.add(
                        Candidate(
                            field_name="totals.net_amount",
                            value=str(amount),
                            confidence=0.85,
                            block=block,
                            page=block.page,
                        )
                    )
                    found_net = True
                    break

        if _IVA_PATTERNS.search(text) and not _TAX_BASE_PATTERNS.search(text):
            for match in _EUR_PATTERN.finditer(text):
                amount = _normalize_money_text(match.group(1))
                if amount is not None and not found_tax:
                    cs.add(
                        Candidate(
                            field_name="totals.tax_amount",
                            value=str(amount),
                            confidence=0.8,
                            block=block,
                            page=block.page,
                        )
                    )
                    found_tax = True
                    break

        if _TOTAL_PATTERNS.search(text):
            for match in _TOTAL_AMOUNT_PATTERN.finditer(text):
                raw = (
                    match.group(2)
                    if match.lastindex and match.lastindex >= 2
                    else match.group(1)
                )
                amount = _normalize_money_text(raw)
                if amount is not None:
                    cs.add(
                        Candidate(
                            field_name="totals.gross_amount",
                            value=str(amount),
                            confidence=0.9,
                            block=block,
                            page=block.page,
                        )
                    )
                    return