from fastapi.testclient import TestClient

from app.api.main import app


def test_extract_invoice_returns_dummy_contract() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/invoices/extract",
        files={"file": ("invoice.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        data={"include_evidence": "true", "include_debug": "true"},
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["invoice"]["supplier"]["legal_name"]
    assert payload["invoice"]["customer"]["tax_id"]
    assert payload["invoice"]["invoice_data"]["number"] == "DUMMY-0001"
    assert payload["invoice"]["tax_lines"][0] == {
        "tax_rate": "21.00",
        "tax_base": "100.00",
        "tax_amount": "21.00",
    }
    assert payload["invoice"]["totals"]["gross_amount"] == "121.00"
    assert payload["confidence"]["global"] == 0.0
    assert "invoice_data.number" in payload["evidence"]
    assert payload["debug"] == {"stage": "dummy_contract"}


def test_extract_invoice_rejects_non_pdf_files() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/invoices/extract",
        files={"file": ("invoice.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_file_type"
