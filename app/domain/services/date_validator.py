from datetime import date, datetime

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")


def parse_invoice_date(value: date | str) -> date:
    """Convierte una fecha de factura soportada a date."""
    if isinstance(value, date):
        return value

    normalized = value.strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Fecha de factura inválida: {value!r}")
