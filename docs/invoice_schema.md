# Contrato inicial de extracción de facturas

El endpoint inicial acepta un PDF por multipart y devuelve siempre una estructura estable. En B1 la respuesta todavía es dummy: fija el contrato para que B2/B3/B4 puedan construir validadores y extracción real sin improvisar el JSON.

## Ruta rápida

1. Arranca la API con `uvicorn app.api.main:app --reload`.
2. Envía un PDF a `POST /api/v1/invoices/extract`.
3. Verifica que la respuesta contiene `invoice`, `confidence`, `warnings`, `errors` y `evidence`.

## Endpoint

| Campo | Valor |
|---|---|
| Método | `POST` |
| Ruta | `/api/v1/invoices/extract` |
| Content-Type | `multipart/form-data` |
| Estado B1 | Dummy válido, sin extracción real |

### Parámetros

| Nombre | Tipo | Obligatorio | Descripción |
|---|---:|---:|---|
| `file` | PDF | Sí | Factura PDF a procesar. |
| `force_ocr` | boolean | No | Fuerza OCR cuando exista pipeline OCR. En B1 solo activa `debug`. |
| `include_evidence` | boolean | No | Incluye evidencias si están disponibles. Por defecto `true`. |
| `include_debug` | boolean | No | Incluye información de depuración. Por defecto `false`. |

## Respuesta principal

```json
{
  "status": "ok",
  "invoice": {
    "supplier": {
      "legal_name": "Proveedor Dummy S.L.",
      "tax_id": "00000000T"
    },
    "customer": {
      "legal_name": "Cliente Dummy S.L.",
      "tax_id": "00000001R"
    },
    "invoice_data": {
      "number": "DUMMY-0001",
      "issue_date": "2000-01-01",
      "due_date": null
    },
    "tax_lines": [
      {
        "tax_rate": "21.00",
        "tax_base": "100.00",
        "tax_amount": "21.00"
      }
    ],
    "totals": {
      "net_amount": "100.00",
      "tax_amount": "21.00",
      "gross_amount": "121.00",
      "advance_amount": null,
      "withholding_amount": null
    }
  },
  "confidence": {
    "global": 0.0,
    "fields": {},
    "needs_review": []
  },
  "warnings": [],
  "errors": [],
  "evidence": {},
  "debug": null
}
```

## Campos obligatorios del MVP

| Campo conceptual | Ruta JSON | Estado B1 |
|---|---|---|
| Fecha de factura | `invoice.invoice_data.issue_date` | Dummy |
| Número de factura | `invoice.invoice_data.number` | Dummy |
| Razón social emisor | `invoice.supplier.legal_name` | Dummy |
| CIF/NIF emisor | `invoice.supplier.tax_id` | Dummy |
| Razón social cliente | `invoice.customer.legal_name` | Dummy |
| CIF/NIF cliente | `invoice.customer.tax_id` | Dummy |
| IVA por línea fiscal | `invoice.tax_lines[].tax_rate` | Dummy |
| Base por línea fiscal | `invoice.tax_lines[].tax_base` | Dummy |
| Importe IVA por línea fiscal | `invoice.tax_lines[].tax_amount` | Dummy |
| Base total | `invoice.totals.net_amount` | Dummy |
| Total factura | `invoice.totals.gross_amount` | Dummy |

## Errores y warnings

Los errores de validación de negocio se modelan como objetos:

```json
{
  "code": "invalid_file_type",
  "message": "El archivo debe ser un PDF.",
  "field": "file"
}
```

Reglas iniciales:

- Si `file` no tiene `content_type` `application/pdf`, la API responde `400`.
- `warnings[]` contiene avisos no bloqueantes.
- `errors[]` queda reservado para errores de extracción o validación representables dentro del contrato.

## Checklist de contrato

- [x] Existe `InvoiceResponse`.
- [x] Existe `Invoice`.
- [x] Existe `Party`.
- [x] Existe `InvoiceData`.
- [x] Existe `TaxLine`.
- [x] Existe `Totals`.
- [x] Existe `Evidence`.
- [x] Existe `ConfidenceReport`.
- [x] Existe endpoint `POST /api/v1/invoices/extract`.
- [x] Hay tests de contrato para respuesta dummy y rechazo de no-PDF.

## Siguiente paso

Implementar B2: validadores de dominio para que los valores reales o propuestos por motores externos NO entren al JSON final sin pasar por reglas fiscales.
