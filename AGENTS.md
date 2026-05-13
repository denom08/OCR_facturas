# Instrucciones para agentes — OCR_facturas

## Fuente principal de contexto

Antes de diseñar, implementar o modificar la solución de extracción de facturas, lee:

```txt
docs/arquitectura-extraccion-facturas.md
```

Ese documento contiene la arquitectura base del proyecto y debe tratarse como la referencia principal hasta que exista documentación más específica.

Para planificar o continuar la implantación por tareas, consulta también:

```txt
docs/plan-implantacion.md
```

Ese plan divide el trabajo en bloques independientes y paralelizables, con tareas, subtareas, dependencias, criterios de aceptación y registro de progreso.

## Qué información encontrarás ahí

El documento explica:

- objetivo del sistema: API local que recibe facturas PDF y devuelve JSON estructurado;
- stack recomendado: Python, FastAPI, Pydantic, PyMuPDF, PaddleOCR, PP-StructureV3, Qwen2.5-VL local, Docker;
- estructura de carpetas propuesta;
- flujo completo de procesamiento de facturas;
- contrato inicial del endpoint `POST /api/v1/invoices/extract`;
- clasificación de PDFs: digital, híbrido, escaneado y con XML embebido;
- modelo de dominio mínimo para facturas;
- capas de extracción: determinista, OCR/layout y VLM local;
- validaciones obligatorias: CIF/NIF/NIE, fechas, importes, IVA, totales y tolerancia decimal;
- sistema de confianza por campo;
- evidencias por campo con texto, página y coordenadas;
- fases recomendadas de implementación;
- estrategia de despliegue local para preservar privacidad;
- primer MVP recomendado.

El documento `docs/plan-implantacion.md` explica:

- bloques de trabajo B0-B12;
- dependencias entre bloques;
- qué tareas pueden ejecutarse en paralelo por varios agentes;
- subtareas verificables por bloque;
- ruta recomendada por iteraciones;
- alcance y criterios de aceptación del MVP;
- tabla de progreso para saber qué está hecho y qué falta.

## Principios técnicos obligatorios

- No construir un flujo simple `PDF -> OCR -> LLM -> JSON`.
- Construir un flujo auditable: `PDF -> parsing/OCR/layout -> documento normalizado -> extracción -> validación -> JSON`.
- La IA local puede proponer valores, pero los validadores de dominio deben decidir si se aceptan.
- Priorizar XML embebido y texto digital cuando existan; usar OCR/VLM solo cuando sea necesario.
- Mantener separación de capas: API, dominio, aplicación e infraestructura.
- Preservar privacidad: los modelos y el procesamiento deben correr localmente.

## Orden recomendado para nuevas tareas

1. Revisar `docs/arquitectura-extraccion-facturas.md`.
2. Revisar `docs/plan-implantacion.md` si la tarea forma parte de la ejecución del roadmap.
3. Confirmar si la tarea afecta schema, pipeline, OCR, VLM, validación o despliegue.
4. Implementar siguiendo arquitectura hexagonal.
5. Añadir o actualizar tests cuando haya lógica de extracción o validación.
6. Actualizar la documentación si cambia una decisión arquitectónica o el orden del plan.

## Nota de estado

El proyecto empezó documentando la arquitectura antes de implementar código. Si faltan carpetas o módulos mencionados en la documentación, créalos de forma incremental según la fase de trabajo correspondiente.
