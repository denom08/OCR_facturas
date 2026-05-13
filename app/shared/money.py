from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def normalize_money(value: Decimal | int | str) -> Decimal:
    """Normaliza importes europeos a Decimal con dos decimales."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)

    if isinstance(value, int):
        return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)

    cleaned = (
        value.strip()
        .replace("€", "")
        .replace("EUR", "")
        .replace("eur", "")
        .replace(" ", "")
    )

    if not cleaned:
        raise ValueError("El importe no puede estar vacío.")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        return Decimal(cleaned).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Importe inválido: {value!r}") from exc
