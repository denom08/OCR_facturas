# Plan de implantación de la API local de extracción de facturas

Este documento convierte la arquitectura base en una ruta de tareas accionable. La lista es deliberadamente adaptable: si durante la implementación descubrimos una forma mejor de separar módulos, cambiar nombres, añadir herramientas o reordenar fases, se actualiza este plan y se continúa.

## Cómo usar este plan

- Usar cada **bloque** como unidad de trabajo independiente cuando sea posible.
- Mantener tests y documentación junto al bloque que los necesita.
- Marcar el estado con: `Pendiente`, `En curso`, `Hecho`, `Bloqueado` o `Replantear`.
- Si una tarea crece demasiado, dividirla antes de implementarla.
- Si se descubre una decisión arquitectónica nueva, actualizar también `docs/arquitectura-extraccion-facturas.md`.

## Decisiones cerradas antes de programar

| Tema | Decisión para MVP-1 |
|---|---|
| Alcance | API, schema estable, validadores, PDF digital, OCR básico, evidencias, confianza y evaluación inicial. |
| Obligatorios | Fecha, número, razón social y CIF de emisor, razón social y CIF de cliente, IVA/base/importe por línea fiscal, base total y total factura. |
| Varios IVAs | Usar lista ordenada: cada elemento conserva porcentaje, base e importe de IVA. |
| Optativos | Adelantos y retenciones. |
| Fixtures | Usar estructura de fixtures, pero no subir facturas PDF/XML/imagen a git. |
| Persistencia | No guardar documentos ni resultados por defecto; solo devolver JSON. |
| Hardware | NVIDIA RTX 5070 Ti, con posibilidad de RTX 5090. |
| Ruta inicial | B0 → B1 → B2; después B3/B4 y B6 según avance. |

## Resumen de dependencias

```txt
B0 Fundaciones
 ├─ B1 Contrato API + schema
 ├─ B2 Dominio + validadores
 ├─ B3 Infraestructura PDF
 │   ├─ B4 Pipeline digital
 │   └─ B5 XML embebido
 ├─ B6 OCR/renderizado
 │   └─ B7 Layout/tablas
 ├─ B8 Resolución de campos/confianza
 │   └─ B9 VLM local
 ├─ B10 Evaluación/dataset dorado
 ├─ B11 Despliegue local
 └─ B12 Observabilidad/operación
```

## Vista rápida por bloques

| Bloque | Objetivo | Paralelizable | Depende de |
|---|---|---:|---|
| B0 | Fundaciones del repo | No | — |
| B1 | Contrato API y schema JSON | Parcial | B0 |
| B2 | Dominio y validadores | Sí | B0, B1 parcial |
| B3 | Infraestructura PDF | Sí | B0 |
| B4 | Pipeline digital | Sí | B1, B2, B3 |
| B5 | XML embebido | Sí | B1, B2, B3 |
| B6 | OCR/renderizado | Sí | B3 |
| B7 | Layout/tablas | Sí | B6 |
| B8 | Resolución, confianza y evidencias | Sí | B1, B2, B4/B6 |
| B9 | VLM local | Sí | B1, B6, B8 parcial |
| B10 | Evaluación y benchmark | Sí | B1, B2 |
| B11 | Docker/despliegue local | Sí | B0, B1 |
| B12 | Observabilidad y operación | Sí | B1, B4/B6 |

---

# B0 — Fundaciones del proyecto

**Objetivo:** dejar el repo preparado para implementar sin improvisar estructura ni herramientas.

**Estado:** Pendiente

## Tareas

- [ ] Crear estructura inicial de carpetas:
  - [ ] `app/api`
  - [ ] `app/domain`
  - [ ] `app/application`
  - [ ] `app/infrastructure`
  - [ ] `app/shared`
  - [ ] `tests/unit`
  - [ ] `tests/integration`
  - [ ] `tests/fixtures`
  - [ ] `scripts`
  - [ ] `docker`
- [ ] Crear `pyproject.toml`.
- [ ] Configurar dependencias iniciales:
  - [ ] `fastapi`
  - [ ] `uvicorn`
  - [ ] `pydantic`
  - [ ] `python-multipart`
  - [ ] `pytest`
  - [ ] `ruff`
- [ ] Crear `README.md` con arranque local mínimo.
- [ ] Crear `.env.example`.
- [ ] Configurar `ruff`.
- [ ] Configurar `pytest`.
- [ ] Añadir prueba mínima de salud del proyecto.

## Resultado verificable

```txt
pytest
```

debe ejecutarse correctamente aunque todavía no exista lógica real de extracción.

## Puede hacerlo en paralelo

- Agente A: estructura + `pyproject.toml`.
- Agente B: README + `.env.example`.
- Agente C: configuración de tests/calidad.

---

# B1 — Contrato API y schema JSON

**Objetivo:** definir exactamente qué entra y qué sale antes de implementar motores de extracción.

**Estado:** Pendiente

## Tareas

- [ ] Diseñar schema Pydantic de respuesta:
  - [ ] `InvoiceResponse`
  - [ ] `Invoice`
  - [ ] `Party`
  - [ ] `InvoiceData`
  - [ ] `TaxLine`
  - [ ] `Totals`
  - [ ] `Evidence`
  - [ ] `ConfidenceReport`
- [ ] Definir campos obligatorios y opcionales.
  - [ ] Obligatorio: fecha de factura.
  - [ ] Obligatorio: número de factura.
  - [ ] Obligatorio: razón social del emisor.
  - [ ] Obligatorio: CIF/NIF del emisor.
  - [ ] Obligatorio: razón social del cliente.
  - [ ] Obligatorio: CIF/NIF del cliente.
  - [ ] Obligatorio: lista ordenada de líneas fiscales con porcentaje IVA, base imponible e importe IVA.
  - [ ] Obligatorio: base imponible total.
  - [ ] Obligatorio: total factura.
  - [ ] Optativo: adelantos.
  - [ ] Optativo: retenciones.
- [ ] Definir formato de errores y warnings.
- [ ] Definir contrato inicial del endpoint:
  - [ ] `POST /api/v1/invoices/extract`
  - [ ] `file`
  - [ ] `force_ocr`
  - [ ] `include_evidence`
  - [ ] `include_debug`
- [ ] Crear endpoint dummy que devuelva un JSON válido.
- [ ] Añadir tests de contrato API.
- [ ] Documentar contrato en `docs/invoice_schema.md`.

## Resultado verificable

- La API acepta un PDF por multipart.
- La respuesta cumple el schema aunque los valores sean dummy.
- Los tests de contrato fallan si cambia la forma del JSON sin intención.

## Puede hacerlo en paralelo

- Agente A: modelos Pydantic.
- Agente B: endpoint FastAPI dummy.
- Agente C: documentación y tests de contrato.

---

# B2 — Dominio y validadores

**Objetivo:** construir las reglas que protegen el resultado final. Esta capa manda sobre la IA.

**Estado:** Pendiente

## Tareas

- [ ] Implementar normalización monetaria:
  - [ ] coma decimal española;
  - [ ] símbolo euro;
  - [ ] separadores de miles;
  - [ ] `Decimal`, nunca `float`.
- [ ] Implementar validador de CIF/NIF/NIE.
- [ ] Implementar validador de fechas.
- [ ] Implementar validador de totales:
  - [ ] base + IVA = total;
  - [ ] múltiples tipos de IVA;
  - [ ] retenciones si aparecen;
  - [ ] tolerancia decimal de `0.01`.
- [ ] Implementar estructura de warnings de dominio.
- [ ] Crear tests unitarios exhaustivos.

## Resultado verificable

Los validadores detectan errores contables y documentos incompletos sin depender de PDF, OCR ni VLM.

## Puede hacerlo en paralelo

- Agente A: CIF/NIF/NIE.
- Agente B: dinero/importes.
- Agente C: totales e IVA.
- Agente D: fechas y warnings.

---

# B3 — Infraestructura PDF base

**Objetivo:** leer y clasificar PDFs antes de decidir si usar texto, XML, OCR o VLM.

**Estado:** Pendiente

## Tareas

- [ ] Crear puerto `PdfReader` en `app/application/ports/pdf_reader.py`.
- [ ] Implementar adaptador con PyMuPDF:
  - [ ] contar páginas;
  - [ ] extraer texto por página;
  - [ ] extraer bloques con coordenadas si es viable;
  - [ ] detectar imágenes por página.
- [ ] Implementar clasificador `PdfKind`:
  - [ ] `DIGITAL`;
  - [ ] `HYBRID`;
  - [ ] `SCANNED`;
  - [ ] `EMBEDDED_XML`.
- [ ] Implementar renderizado básico de páginas a imagen.
- [ ] Añadir tests con PDFs fixture mínimos.

## Resultado verificable

Dado un PDF, el sistema informa tipo, páginas, texto extraíble y si necesita OCR.

## Puede hacerlo en paralelo

- Agente A: puerto e implementación PyMuPDF.
- Agente B: clasificador PDF.
- Agente C: renderizador de páginas.
- Agente D: fixtures y tests.

---

# B4 — Pipeline para PDFs digitales

**Objetivo:** extraer facturas con texto real sin OCR.

**Estado:** Pendiente

## Tareas

- [ ] Crear representación de documento normalizado:
  - [ ] páginas;
  - [ ] bloques;
  - [ ] texto;
  - [ ] coordenadas;
  - [ ] fuente de extracción.
- [ ] Crear extractor de candidatos por patrones:
  - [ ] número de factura;
  - [ ] fecha;
  - [ ] CIF/NIF/NIE;
  - [ ] razón social;
  - [ ] base imponible;
  - [ ] IVA;
  - [ ] total.
- [ ] Añadir heurísticas para emisor vs cliente.
- [ ] Vincular candidatos con evidencias.
- [ ] Pasar candidatos por validadores B2.
- [ ] Añadir tests con facturas digitales.

## Resultado verificable

Una factura digital sencilla devuelve JSON real con campos principales y evidencias.

## Puede hacerlo en paralelo

- Agente A: documento normalizado.
- Agente B: patrones de identificación fiscal/fechas.
- Agente C: patrones de importes/IVA/totales.
- Agente D: evidencias y tests.

---

# B5 — XML embebido y formatos electrónicos

**Objetivo:** priorizar datos estructurados cuando existan dentro del PDF.

**Estado:** Pendiente

## Tareas

- [ ] Investigar extracción de adjuntos PDF con `pikepdf`/`pypdf`.
- [ ] Detectar XML embebido.
- [ ] Identificar formato:
  - [ ] Facturae;
  - [ ] UBL;
  - [ ] CII / Factur-X / ZUGFeRD.
- [ ] Crear parser mínimo para Facturae.
- [ ] Mapear XML al schema `Invoice`.
- [ ] Validar XML mapeado con reglas B2.
- [ ] Añadir tests con XML fixture sintético si no tenemos facturas reales.

## Resultado verificable

Si el PDF contiene XML reconocido, se extrae la factura desde XML y se marca como fuente principal.

## Puede hacerlo en paralelo

- Agente A: extracción de adjuntos.
- Agente B: parser Facturae.
- Agente C: parser UBL/CII inicial.
- Agente D: mapeo y tests.

---

# B6 — OCR y renderizado para PDFs escaneados

**Objetivo:** convertir páginas imagen en texto con coordenadas y confianza.

**Estado:** Pendiente

## Tareas

- [ ] Definir puerto `OcrEngine`.
- [ ] Integrar PaddleOCR básico.
- [ ] Convertir páginas PDF a imágenes para OCR.
- [ ] Normalizar salida OCR a bloques internos.
- [ ] Guardar confianza por bloque.
- [ ] Añadir opción `force_ocr`.
- [ ] Añadir tests con imágenes/PDFs escaneados simples.

## Resultado verificable

Un PDF escaneado produce documento normalizado con texto, coordenadas y confianza.

## Puede hacerlo en paralelo

- Agente A: puerto OCR y adaptador.
- Agente B: renderizado y pipeline de imágenes.
- Agente C: normalizador de salida OCR.
- Agente D: tests/fixtures escaneados.

---

# B7 — Layout, tablas y líneas de IVA

**Objetivo:** entender mejor la estructura visual de facturas con tablas y múltiples impuestos.

**Estado:** Pendiente

## Tareas

- [ ] Definir puerto `LayoutAnalyzer`.
- [ ] Integrar PP-StructureV3 o motor equivalente.
- [ ] Detectar tablas.
- [ ] Extraer celdas con coordenadas.
- [ ] Identificar tablas de totales e impuestos.
- [ ] Resolver múltiples tipos de IVA.
- [ ] Añadir tests con tablas sintéticas.

## Resultado verificable

Una factura con varios tipos de IVA genera `tax_lines[]` correctas.

## Puede hacerlo en paralelo

- Agente A: puerto layout.
- Agente B: integración PP-StructureV3.
- Agente C: extractor de tablas fiscales.
- Agente D: fixtures y evaluación de tablas.

---

# B8 — Resolución de campos, confianza y evidencias

**Objetivo:** fusionar candidatos de XML, PDF digital, OCR y layout en una factura final coherente.

**Estado:** Pendiente

## Tareas

- [ ] Definir modelo `CandidateField`.
- [ ] Definir prioridades de fuentes:
  - [ ] XML;
  - [ ] texto digital;
  - [ ] OCR/layout;
  - [ ] VLM.
- [ ] Resolver conflictos entre candidatos.
- [ ] Calcular confianza por campo.
- [ ] Calcular confianza global.
- [ ] Generar `needs_review`.
- [ ] Asociar evidencias a cada campo final.
- [ ] Añadir tests de resolución de conflictos.

## Resultado verificable

El sistema puede recibir varios candidatos para un mismo campo y escoger el mejor con explicación, confianza y warning si hay duda.

## Puede hacerlo en paralelo

- Agente A: modelo de candidatos.
- Agente B: estrategia de prioridad/conflictos.
- Agente C: confianza global y por campo.
- Agente D: evidencias y warnings.

---

# B9 — VLM local para casos complejos

**Objetivo:** usar Qwen2.5-VL local como apoyo cuando OCR/reglas no basten.

**Estado:** Pendiente

## Tareas

- [ ] Definir puerto `InvoiceExtractor` para modelos IA.
- [ ] Elegir modo inicial de serving:
  - [ ] Transformers directo para MVP; o
  - [ ] vLLM si priorizamos servicio separado.
- [ ] Crear prompt estricto con schema JSON.
- [ ] Crear parser robusto de salida JSON.
- [ ] Definir cuándo invocar VLM:
  - [ ] campos obligatorios faltantes;
  - [ ] baja confianza;
  - [ ] factura escaneada compleja;
  - [ ] tabla fiscal no resuelta.
- [ ] Validar siempre la salida con B2 y B8.
- [ ] Añadir tests con mocks del modelo.

## Resultado verificable

El VLM puede proponer valores, pero el sistema no acepta valores inválidos ni inventados sin evidencia o validación.

## Puede hacerlo en paralelo

- Agente A: puerto y mock del extractor IA.
- Agente B: prompt y schema de salida.
- Agente C: integración local Qwen.
- Agente D: reglas de invocación y tests.

---

# B10 — Dataset dorado, evaluación y benchmark

**Objetivo:** saber si el sistema mejora o empeora con datos reales. Sin métricas, solo estamos adivinando.

**Estado:** Pendiente

## Tareas

- [ ] Crear estructura de fixtures:
  - [ ] `tests/fixtures/digital`;
  - [ ] `tests/fixtures/hybrid`;
  - [ ] `tests/fixtures/scanned`;
  - [ ] `tests/fixtures/expected_json`.
- [ ] Crear formato de ground truth.
- [ ] Mantener facturas PDF/XML/imagen fuera de git.
- [ ] Versionar solo datos seguros no sensibles, por ejemplo `expected_json` sintético o plantillas sin datos reales.
- [ ] Crear script `scripts/evaluate_extraction.py`.
- [ ] Medir precisión por campo:
  - [ ] CIF/NIF exact match;
  - [ ] fechas exact match;
  - [ ] importes con tolerancia;
  - [ ] razón social con fuzzy match;
  - [ ] tax lines.
- [ ] Crear reporte de errores por tipo de factura.
- [ ] Documentar evaluación en `docs/evaluation.md`.

## Resultado verificable

Podemos ejecutar un comando y obtener precisión por campo, no una impresión subjetiva.

## Puede hacerlo en paralelo

- Agente A: estructura de dataset.
- Agente B: script de evaluación.
- Agente C: métricas por campo.
- Agente D: documentación y reporte.

---

# B11 — Despliegue local y contenedores

**Objetivo:** ejecutar todo localmente preservando privacidad.

**Estado:** Pendiente

## Tareas

- [ ] Crear `docker/api.Dockerfile`.
- [ ] Crear `docker-compose.yml` mínimo con API.
- [ ] Añadir volumen temporal para PDFs procesados.
- [ ] Preparar servicio opcional `vlm`.
- [ ] Preparar servicio opcional `redis` para fase asíncrona.
- [ ] Documentar requisitos de GPU.
- [ ] Documentar arranque local.

## Resultado verificable

El proyecto arranca localmente con Docker y expone la API sin enviar datos fuera de la máquina.

## Puede hacerlo en paralelo

- Agente A: contenedor API.
- Agente B: docker-compose.
- Agente C: servicio VLM opcional.
- Agente D: documentación de despliegue.

---

# B12 — Observabilidad, debug y operación

**Objetivo:** facilitar depuración, auditoría y revisión humana.

**Estado:** Pendiente

## Tareas

- [ ] Añadir logging estructurado por request.
- [ ] Generar `request_id`.
- [ ] Registrar tiempos por etapa:
  - [ ] clasificación PDF;
  - [ ] extracción texto;
  - [ ] OCR;
  - [ ] layout;
  - [ ] VLM;
  - [ ] validación.
- [ ] Añadir modo `include_debug`.
- [ ] Guardar opcionalmente imágenes con cajas detectadas en modo debug.
- [ ] Añadir errores legibles para usuario.
- [ ] Añadir métricas básicas de rendimiento.

## Resultado verificable

Cuando una factura falla o genera baja confianza, podemos saber en qué etapa ocurrió y por qué.

## Puede hacerlo en paralelo

- Agente A: logging/request_id.
- Agente B: tiempos por etapa.
- Agente C: debug visual.
- Agente D: errores y métricas.

---

# Ruta recomendada de ejecución

## Iteración 1 — Cimientos y contrato

1. B0 — Fundaciones.
2. B1 — Contrato API y schema.
3. B2 — Validadores de dominio básicos.

**Salida:** API dummy, schema estable y validadores unitarios.

## Iteración 2 — Primer valor real: PDF digital

1. B3 — Infraestructura PDF.
2. B4 — Pipeline digital.
3. B8 — Resolución básica, confianza y evidencias.
4. B10 — Primeras fixtures digitales.

**Salida:** extracción real de facturas digitales sencillas.

## Iteración 3 — Factura electrónica y robustez contable

1. B5 — XML embebido.
2. Ampliación de B2 para múltiples impuestos/retenciones.
3. Ampliación de B10 con fixtures XML.

**Salida:** si hay XML, el sistema lo prioriza y valida.

## Iteración 4 — Escaneados simples

1. B6 — OCR/renderizado.
2. Reutilizar B4 sobre texto OCR.
3. Ampliar B8 con confianza OCR.
4. Ampliar B10 con escaneados.

**Salida:** soporte inicial para PDFs imagen.

## Iteración 5 — Tablas, layout y múltiples IVA

1. B7 — Layout/tablas.
2. Mejorar extracción de `tax_lines`.
3. Añadir fixtures con 21%, 10%, 4% y retenciones.

**Salida:** facturas fiscalmente más complejas.

## Iteración 6 — VLM local y casos difíciles

1. B9 — VLM local.
2. Usar VLM solo por reglas de invocación.
3. Validar todo con B2/B8.

**Salida:** mejora en facturas visualmente complejas sin perder control.

## Iteración 7 — Operación local

1. B11 — Docker/despliegue.
2. B12 — Observabilidad/debug.
3. Benchmarks de rendimiento.

**Salida:** sistema local operable y depurable.

---

# Primer MVP propuesto

## Alcance del MVP

- API FastAPI con `POST /api/v1/invoices/extract`.
- Schema JSON estable.
- Validadores de CIF/NIF/NIE, fechas, importes, IVA y total.
- Extracción de PDFs digitales.
- OCR básico para escaneados simples.
- Evidencias por campo.
- Confianza por campo.
- Fixtures y evaluación inicial.
- Sin persistencia de facturas ni resultados por defecto; solo respuesta JSON.

## Campos obligatorios del MVP

- Fecha de factura.
- Número de factura.
- Razón social del emisor.
- CIF/NIF del emisor.
- Razón social del cliente.
- CIF/NIF del cliente.
- Porcentaje de IVA aplicado por línea fiscal.
- Importe de IVA por línea fiscal.
- Base imponible por línea fiscal.
- Base imponible total.
- Total factura.

Si hay varios IVAs, se representan como lista ordenada, conservando el orden detectado en la factura.

## Campos optativos del MVP

- Adelantos.
- Retenciones.

## Fuera del MVP

- VLM local en producción.
- Procesamiento asíncrono.
- UI de revisión humana.
- Soporte completo de todos los formatos XML europeos.
- Optimización avanzada de GPU.
- Persistencia en base de datos.

## Criterio de aceptación del MVP

El MVP se considera listo cuando:

- [ ] procesa al menos 10 facturas digitales;
- [ ] procesa al menos 5 facturas escaneadas simples;
- [ ] devuelve JSON válido en todos los casos;
- [ ] marca campos dudosos con `needs_review`;
- [ ] incluye evidencias para campos principales;
- [ ] rechaza o advierte totales que no cuadran;
- [ ] no persiste facturas ni resultados por defecto;
- [ ] puede ejecutarse localmente sin servicios externos.

---

# Registro de progreso

Usar esta tabla para mantener visibilidad del avance.

| Bloque | Estado | Responsable | Notas |
|---|---|---|---|
| B0 Fundaciones | Pendiente | — | — |
| B1 Contrato API + schema | Pendiente | — | — |
| B2 Dominio + validadores | Pendiente | — | — |
| B3 Infraestructura PDF | Pendiente | — | — |
| B4 Pipeline digital | Pendiente | — | — |
| B5 XML embebido | Pendiente | — | — |
| B6 OCR/renderizado | Pendiente | — | — |
| B7 Layout/tablas | Pendiente | — | — |
| B8 Resolución/confianza/evidencias | Pendiente | — | — |
| B9 VLM local | Pendiente | — | — |
| B10 Evaluación/benchmark | Pendiente | — | — |
| B11 Despliegue local | Pendiente | — | — |
| B12 Observabilidad/operación | Pendiente | — | — |

## Regla de cambio

Si durante la implementación una tarea deja de tener sentido, no se fuerza. Se marca como `Replantear`, se explica el motivo en `Notas` y se actualiza el plan. El objetivo no es obedecer un documento rígido; el objetivo es mantener una ruta clara mientras aprendemos del código real y de las facturas reales.
