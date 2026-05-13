import re

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_CONTROL_LETTERS = "JABCDEFGHI"
CIF_LETTER_CONTROL_TYPES = set("KPQRSNW")
CIF_DIGIT_CONTROL_TYPES = set("ABEH")


def normalize_tax_id(value: str) -> str:
    return re.sub(r"[\s\-.]", "", value).upper()


def is_valid_tax_id(value: str) -> bool:
    tax_id = normalize_tax_id(value)
    return is_valid_nif(tax_id) or is_valid_nie(tax_id) or is_valid_cif(tax_id)


def is_valid_nif(value: str) -> bool:
    tax_id = normalize_tax_id(value)
    if not re.fullmatch(r"\d{8}[A-Z]", tax_id):
        return False

    number = int(tax_id[:8])
    return tax_id[-1] == NIF_LETTERS[number % 23]


def is_valid_nie(value: str) -> bool:
    tax_id = normalize_tax_id(value)
    if not re.fullmatch(r"[XYZ]\d{7}[A-Z]", tax_id):
        return False

    prefix = {"X": "0", "Y": "1", "Z": "2"}[tax_id[0]]
    number = int(prefix + tax_id[1:8])
    return tax_id[-1] == NIF_LETTERS[number % 23]


def is_valid_cif(value: str) -> bool:
    tax_id = normalize_tax_id(value)
    if not re.fullmatch(r"[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]", tax_id):
        return False

    entity_type = tax_id[0]
    digits = tax_id[1:8]
    control = tax_id[-1]

    odd_sum = sum(_sum_digits(int(digit) * 2) for digit in digits[0::2])
    even_sum = sum(int(digit) for digit in digits[1::2])
    control_digit = (10 - ((odd_sum + even_sum) % 10)) % 10
    control_letter = CIF_CONTROL_LETTERS[control_digit]

    if entity_type in CIF_LETTER_CONTROL_TYPES:
        return control == control_letter
    if entity_type in CIF_DIGIT_CONTROL_TYPES:
        return control == str(control_digit)

    return control in {str(control_digit), control_letter}


def _sum_digits(value: int) -> int:
    return sum(int(digit) for digit in str(value))
