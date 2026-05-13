import pytest

from app.domain.services.tax_id_validator import (
    is_valid_cif,
    is_valid_nie,
    is_valid_nif,
    is_valid_tax_id,
)


@pytest.mark.parametrize("tax_id", ["00000000T", "12345678Z"])
def test_valid_nif(tax_id: str) -> None:
    assert is_valid_nif(tax_id)
    assert is_valid_tax_id(tax_id)


@pytest.mark.parametrize("tax_id", ["00000000A", "12345678A"])
def test_invalid_nif(tax_id: str) -> None:
    assert not is_valid_nif(tax_id)


@pytest.mark.parametrize("tax_id", ["X0000000T", "Y0000000Z", "Z0000000M"])
def test_valid_nie(tax_id: str) -> None:
    assert is_valid_nie(tax_id)
    assert is_valid_tax_id(tax_id)


@pytest.mark.parametrize("tax_id", ["B99286320", "A58818501", "P2807900B"])
def test_valid_cif(tax_id: str) -> None:
    assert is_valid_cif(tax_id)
    assert is_valid_tax_id(tax_id)


@pytest.mark.parametrize("tax_id", ["B99286321", "P2807900A", "texto"])
def test_invalid_cif(tax_id: str) -> None:
    assert not is_valid_cif(tax_id)
