# Evaluación del sistema de extracción de facturas

Este documento describe cómo funciona la evaluación del sistema, qué métricas se usan y cómo interpretar los resultados.

## Conceptos clave

### Dataset dorado (golden dataset)

Conjunto de facturas con su ground truth (respuesta esperada) asoci ada. Permite medir objetivamente si el sistema mejora o empeora con cada cambio.

**Estructura del dataset:**

```
tests/fixtures/
  digital/          # PDFs digitales reales para evaluación local (no en git)
  hybrid/           # PDFs híbridos reales para evaluación local (no en git)
  scanned/         # PDFs escaneados reales para evaluación local (no en git)
  expected_json/   # Ground truths sintéticos VERSIONADOS
    digital.json
    hybrid.json
    scanned.json
```

**Formato del ground truth** (`expected_json/*.json`):

```json
[
  {
    "invoice_file": "digital_synth_001.pdf",
    "invoice_type": "digital",
    "expected": {
      "invoice_data": { "number": "...", "issue_date": "...", "due_date": null },
      "supplier": { "legal_name": "...", "tax_id": "..." },
      "customer": { "legal_name": "...", "tax_id": "..." },
      "tax_lines": [
        { "tax_rate": "21.00", "tax_base": "1000.00", "tax_amount": "210.00" }
      ],
      "totals": {
        "net_amount": "1000.00",
        "tax_amount": "210.00",
        "gross_amount": "1210.00",
        "advance_amount": null,
        "withholding_amount": null
      }
    }
  }
]
```

## Métricas por campo

| Campo | Métrica | Descripción |
|---|---|---|
| `supplier.tax_id` | exact match | CIF/NIF/NIE debe ser idéntico |
| `customer.tax_id` | exact match | CIF/NIF/NIE debe ser idéntico |
| `invoice_data.number` | exact match | Número de factura idéntico |
| `invoice_data.issue_date` | exact match | Fecha ISO idéntica |
| `supplier.legal_name` | fuzzy match | Normalización + similaridad ≥ 85% |
| `customer.legal_name` | fuzzy match | Normalización + similaridad ≥ 85% |
| `tax_lines` | structural + tolerance | Mismo nº líneas, tasas exactas, importes con tolerancia 0.01€ |
| `totals` | tolerance | net_amount, tax_amount, gross_amount con tolerancia 0.01€ |

### Exact match

El valor predicho debe ser **exactamente** igual al esperado. Se usa para identificadores (CIF/NIF, números, fechas).

### Fuzzy match (razón social)

1. Normalización: eliminación de sufijos legales (`S.L.`, `S.A.`), paso a mayúsculas, eliminación de espacios多余的.
2. Si son idénticos tras normalización → match.
3. Si no, se calcula `SequenceMatcher.ratio()`. Si ≥ 0.85 → match.
4. Esto permite aceptar variaciones menores sin ser demasiado laxo.

### Tolerancia decimal

Para importes monetarios se usa tolerancia de `0.01 €`. Esto cubre errores de redondeo comunes en la extracción.

### Structural match (tax_lines)

1. El número de líneas debe ser idéntico.
2. La `tax_rate` de cada línea debe ser exacta.
3. `tax_base` y `tax_amount` deben estar dentro de la tolerancia.

## Script de evaluación

```bash
python scripts/evaluate_extraction.py \
  --ground-truth tests/fixtures/expected_json/digital.json \
  --predictions output/predictions/digital \
  --type digital \
  --verbose
```

### Opciones

| Opción | Descripción |
|---|---|
| `--ground-truth`, `-g` | Ruta al archivo JSON de ground truth |
| `--predictions`, `-p` | Directorio con archivos JSON predichos |
| `--type`, `-t` | Tipo de factura (digital, hybrid, scanned) |
| `--verbose`, `-v` | Muestra errores detallados por factura |
| `--output`, `-o` | Guarda el reporte en JSON |

### Salida esperada

```
======================================================================
EVALUATION REPORT
======================================================================

## Per-type Error Summary
  digital           40 fields    0 errors  accuracy:  100.0%

## Per-invoice Results
  [OK] digital_synth_001.pdf                         score: 100.00%
  [OK] digital_synth_002.pdf                         score: 100.00%

## Field-level Accuracy
  invoice_data.number                   100.0%
  invoice_data.issue_date               100.0%
  supplier.legal_name                   100.0%
  supplier.tax_id                       100.0%
  customer.legal_name                   100.0%
  customer.tax_id                       100.0%
  tax_lines                             100.0%
  totals                                100.0%

## Global Accuracy: 100.00%
======================================================================
```

## Política de privacidad

**Las facturas PDF/XML/imagen reales NO se suben a git.**

- El directorio `tests/fixtures/` solo contiene `.gitkeep` y este README.
- Los ground truths en `expected_json/` son datos **sintéticos** y seguros.
- Para añadir facturas reales locales, agrégalas a `.gitignore` y usa variables locales.

## Ejecutar tests del evaluador

```bash
python -m pytest tests/unit/test_evaluator.py -v
```

## Flujo de evaluación en CI/CD

1. Ejecutar el pipeline sobre el dataset de evaluación.
2. Guardar los JSONs resultantes en `output/predictions/{type}/`.
3. Ejecutar `scripts/evaluate_extraction.py` contra el ground truth.
4. Fallar la build si `global_accuracy` baja del umbral configurado (ej: 90%).

## Extensión futura

- Añadir PDFs reales a `tests/fixtures/digital/` (no versionados).
- Ampliar ground truths con más variantes.
- Medir latencia por etapa del pipeline.
- Añadir métricas de precision/recall por campo.