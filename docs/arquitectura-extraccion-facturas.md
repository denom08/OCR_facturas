# Arquitectura para API local de extracción de facturas PDF

Este documento recoge el plan base para construir una API web que reciba facturas en PDF y devuelva un JSON estructurado con emisor, cliente, CIF/NIF, bases imponibles, IVA, totales y evidencias. La decisión principal es usar una arquitectura por capas: primero extracción determinista, después OCR/layout, después modelo local si hace falta, y siempre validación contable al final.

## Decisión principal

Usaremos:

> **Python + FastAPI + arquitectura hexagonal + pipeline de extracción por etapas.**

La IA local no será la única fuente de verdad. Se usará como apoyo para casos ambiguos, pero todos los datos extraídos deberán pasar por validadores de dominio.

## Stack recomendado

| Área | Tecnología |
|---|---|
| API web | FastAPI |
| Schemas y validación | Pydantic v2 |
| PDF digital | PyMuPDF, pypdf, pikepdf |
| OCR y layout | PaddleOCR, PP-StructureV3, opcional PaddleOCR-VL |
| Modelo visual local | Qwen2.5-VL-7B-Instruct |
| Serving IA | vLLM o Transformers |
| Procesamiento asíncrono | Inicialmente síncrono; luego RQ/Celery + Redis |
| Tests | pytest |
| Calidad | ruff, mypy, pre-commit |
| Contenedores | Docker / Docker Compose |

## Estructura de carpetas propuesta

```txt
ocr_facturas/
│
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   └── invoices.py
│   │   ├── dependencies.py
│   │   └── main.py
│   │
│   ├── domain/
│   │   ├── models/
│   │   │   ├── invoice.py
│   │   │   ├── party.py
│   │   │   ├── tax.py
│   │   │   └── evidence.py
│   │   ├── services/
│   │   │   ├── invoice_validator.py
│   │   │   ├── nif_cif_validator.py
│   │   │   └── totals_validator.py
│   │   └── errors.py
│   │
│   ├── application/
│   │   ├── use_cases/
│   │   │   └── process_invoice.py
│   │   ├── ports/
│   │   │   ├── pdf_reader.py
│   │   │   ├── ocr_engine.py
│   │   │   ├── layout_analyzer.py
│   │   │   ├── invoice_extractor.py
│   │   │   └── storage.py
│   │   └── pipeline/
│   │       ├── classify_pdf.py
│   │       ├── normalize_document.py
│   │       ├── extract_candidates.py
│   │       ├── resolve_fields.py
│   │       └── validate_invoice.py
│   │
│   ├── infrastructure/
│   │   ├── pdf/
│   │   │   ├── pymupdf_reader.py
│   │   │   ├── embedded_xml_extractor.py
│   │   │   └── pdf_renderer.py
│   │   ├── ocr/
│   │   │   ├── paddle_ocr_engine.py
│   │   │   ├── paddle_structure_engine.py
│   │   │   └── docling_engine.py
│   │   ├── llm/
│   │   │   ├── qwen_vl_extractor.py
│   │   │   ├── prompt_templates.py
│   │   │   └── structured_output.py
│   │   ├── storage/
│   │   │   ├── local_storage.py
│   │   │   └── temp_storage.py
│   │   └── config.py
│   │
│   └── shared/
│       ├── logging.py
│       ├── money.py
│       ├── confidence.py
│       └── text_utils.py
│
├── workers/
│   └── invoice_worker.py
│
├── models/
│   ├── paddleocr/
│   ├── qwen/
│   └── README.md
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   │   ├── digital/
│   │   ├── scanned/
│   │   ├── hybrid/
│   │   └── expected_json/
│   └── golden/
│
├── scripts/
│   ├── benchmark_invoices.py
│   ├── build_golden_dataset.py
│   └── evaluate_extraction.py
│
├── docs/
│   ├── architecture.md
│   ├── invoice_schema.md
│   ├── extraction_pipeline.md
│   └── evaluation.md
│
├── docker/
│   ├── api.Dockerfile
│   ├── worker.Dockerfile
│   └── vlm.Dockerfile
│
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── .env.example
```

## Flujo de procesamiento

```txt
1. Recibir PDF
2. Guardar temporalmente
3. Clasificar PDF
4. Extraer XML embebido si existe
5. Extraer texto digital si existe
6. Renderizar páginas necesarias
7. OCR/layout si hace falta
8. Normalizar documento
9. Extraer candidatos
10. Resolver campos finales
11. Validar importes y CIF/NIF
12. Devolver JSON con confianza y evidencias
```

## Endpoint principal

```http
POST /api/v1/invoices/extract
Content-Type: multipart/form-data
```

Parámetros recomendados:

```txt
file: factura.pdf
force_ocr: false
include_evidence: true
include_debug: false
```

Respuesta esperada:

```json
{
  "status": "ok",
  "invoice": {},
  "confidence": {},
  "warnings": [],
  "evidence": {}
}
```

## Clasificación del PDF

Tipos previstos:

```python
class PdfKind(str, Enum):
    DIGITAL = "digital"
    HYBRID = "hybrid"
    SCANNED = "scanned"
    EMBEDDED_XML = "embedded_xml"
```

| Señal | Interpretación |
|---|---|
| XML embebido | Usar XML como fuente principal |
| Mucho texto extraíble | PDF digital |
| Poco texto y muchas imágenes | PDF híbrido |
| Casi nada de texto y página como imagen | PDF escaneado |

## Modelo de dominio mínimo

```python
class Invoice(BaseModel):
    supplier: Party
    customer: Party
    invoice_data: InvoiceData
    tax_lines: list[TaxLine]
    totals: Totals
    line_items: list[InvoiceLine] = []
    evidence: dict[str, Evidence] = {}
    confidence: ConfidenceReport
    warnings: list[str] = []
```

Campos mínimos:

```txt
supplier.legal_name
supplier.tax_id
customer.legal_name
customer.tax_id
invoice_data.number
invoice_data.issue_date
invoice_data.due_date
```

## Capas de extracción

### 1. Extracción determinista

Para PDFs digitales o XML embebido.

Usar:

- regex para CIF/NIF;
- regex para fechas;
- regex para importes;
- detección de palabras clave:
  - Base imponible;
  - IVA;
  - Total factura;
  - NIF/CIF;
  - Cliente;
  - Proveedor;
  - Factura nº.

Esta capa debe tener prioridad porque es la más fiable cuando existe texto real o XML estructurado.

### 2. OCR y layout

Para PDFs escaneados o híbridos.

Usar PaddleOCR para obtener:

- texto;
- coordenadas;
- bloques;
- tablas;
- confianza por bloque.

Ejemplo de documento normalizado:

```json
{
  "pages": [
    {
      "page_number": 1,
      "blocks": [
        {
          "text": "TOTAL FACTURA 1.210,00 €",
          "bbox": [100, 700, 500, 730],
          "type": "text",
          "confidence": 0.94
        }
      ]
    }
  ]
}
```

### 3. Modelo visual local

Para casos ambiguos:

- emisor frente a cliente;
- logos;
- cabeceras visuales;
- tablas mal detectadas;
- diseños raros.

Modelo recomendado:

```txt
Qwen2.5-VL-7B-Instruct
```

Regla obligatoria:

> El modelo puede proponer datos, pero el dominio debe validarlos antes de aceptarlos.

Prompt base:

```txt
Extrae los campos de esta factura.
Devuelve SOLO JSON válido conforme al schema.
No inventes valores.
Si no estás seguro, usa null.
Incluye evidencias textuales.
```

## Validación obligatoria

Validadores mínimos:

```txt
CIF/NIF/NIE válido
fecha válida
moneda válida
base * iva = cuota
suma cuotas = iva_total
base_total + iva_total - retenciones = total_factura
```

Ejemplo conceptual:

```python
expected_total = net_amount + tax_amount - withholding_amount

if abs(expected_total - gross_amount) > Decimal("0.01"):
    warnings.append("El total no cuadra con base + IVA - retenciones")
```

## Sistema de confianza

Cada campo debe tener confianza individual:

```json
{
  "confidence": {
    "global": 0.91,
    "fields": {
      "supplier.tax_id": 0.98,
      "customer.legal_name": 0.74,
      "totals.gross_amount": 0.99
    },
    "needs_review": [
      "customer.legal_name"
    ]
  }
}
```

## Evidencias

Siempre que sea posible, cada campo debe apuntar a su origen:

```json
{
  "evidence": {
    "supplier.tax_id": {
      "text": "B12345678",
      "page": 1,
      "bbox": [120, 80, 220, 105]
    }
  }
}
```

Esto permite depurar, auditar y revisar manualmente los campos dudosos.

## Fases de implementación

### Fase 1: Base del proyecto

Objetivo: API funcional con estructura limpia.

- Crear FastAPI.
- Definir schemas Pydantic.
- Crear endpoint de subida PDF.
- Añadir storage temporal.
- Añadir tests mínimos.

Resultado esperado:

```txt
Subo PDF -> recibo respuesta dummy estructurada
```

### Fase 2: PDFs digitales

Objetivo: extraer facturas con texto real.

- Integrar PyMuPDF.
- Clasificar PDF digital.
- Extraer texto por páginas.
- Extraer candidatos con regex.
- Validar CIF/NIF, fechas e importes.

Resultado esperado:

```txt
Factura digital -> JSON real con campos principales
```

### Fase 3: XML embebido

Objetivo: aprovechar factura electrónica cuando exista.

- Detectar adjuntos PDF.
- Extraer XML.
- Parsear Facturae / UBL / CII si aplica.
- Mapear XML al schema interno.

Resultado esperado:

```txt
Factura electrónica -> JSON casi perfecto
```

### Fase 4: OCR escaneado

Objetivo: soportar PDFs imagen.

- Renderizar PDF a imagen.
- Integrar PaddleOCR.
- Generar documento normalizado con bloques y coordenadas.
- Reutilizar extractores de candidatos sobre texto OCR.

Resultado esperado:

```txt
Factura escaneada -> JSON con confianza y evidencias
```

### Fase 5: Layout y tablas

Objetivo: entender líneas de IVA y tablas.

- Integrar PP-StructureV3.
- Detectar tablas.
- Extraer bases, tipos de IVA y cuotas.
- Resolver múltiples tipos de IVA.

Resultado esperado:

```txt
Factura con IVA 21%, 10%, 4% -> tax_lines correctas
```

### Fase 6: VLM local

Objetivo: resolver casos complejos.

- Servir Qwen2.5-VL local.
- Crear extractor con schema estricto.
- Usarlo solo cuando falten campos clave o haya baja confianza.

Resultado esperado:

```txt
Casos ambiguos -> mejora de extracción sin perder control
```

### Fase 7: Evaluación

Objetivo: medir precisión real.

Crear dataset dorado:

```txt
tests/fixtures/
  digital/
  scanned/
  hybrid/
  expected_json/
```

Métricas:

| Campo | Métrica |
|---|---|
| CIF/NIF | exact match |
| Razón social | fuzzy match |
| Fechas | exact match |
| Bases | tolerancia 0.01 € |
| IVA | tolerancia 0.01 € |
| Total | tolerancia 0.01 € |

## Despliegue local

Para preservar privacidad, todos los servicios deben correr localmente.

Servicios esperados en Docker Compose:

```yaml
services:
  api:
    build: docker/api.Dockerfile
    ports:
      - "8000:8000"

  vlm:
    build: docker/vlm.Dockerfile
    ports:
      - "8001:8001"
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  redis:
    image: redis:7
```

En el MVP se puede empezar sin Redis ni worker.

## Orden recomendado de trabajo

```txt
1. Definir schema final de factura
2. Crear API mínima
3. Implementar PDF digital
4. Añadir validadores contables
5. Añadir OCR
6. Añadir layout/tablas
7. Añadir VLM local
8. Crear benchmark
9. Optimizar rendimiento
```

## Primer entregable realista

El primer hito debe ser:

> MVP que procesa PDFs digitales y escaneados simples, devuelve JSON validado con evidencias y marca campos dudosos.

Alcance inicial:

- un endpoint;
- PDF digital;
- OCR básico;
- CIF/NIF;
- emisor;
- cliente;
- número de factura;
- fecha;
- base imponible;
- IVA;
- total;
- evidencias;
- tests con 10-20 facturas.

## Principio de diseño

No construir:

```txt
PDF -> OCR -> prompt a LLM -> JSON
```

Construir:

```txt
PDF -> parsing/OCR/layout -> documento normalizado -> extracción -> validación -> JSON auditable
```

La diferencia es importante: en facturación, el modelo puede ayudar, pero los validadores de dominio y las reglas contables deben proteger el resultado final.
