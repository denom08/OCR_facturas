# OCR Facturas

API local para recibir facturas en PDF y devolver un JSON estructurado con campos fiscales, evidencias y confianza.

## Principio de arquitectura

El sistema NO debe ser un flujo directo `PDF -> OCR -> LLM -> JSON`.

La ruta base es:

```txt
PDF -> parsing/OCR/layout -> documento normalizado -> extracción -> validación -> JSON auditable
```

La IA local puede proponer valores, pero los validadores de dominio deciden si se aceptan.

## Arranque local mínimo

Requisitos:

- Python 3.10 o superior.

Instalación en entorno virtual:

```bash
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

Ejecutar tests:

```bash
pytest
```

Arrancar API:

```bash
uvicorn app.api.main:app --reload
```

Comprobar salud:

```bash
curl http://127.0.0.1:8000/health
```

## Documentación principal

- `docs/arquitectura-extraccion-facturas.md`: arquitectura base y decisiones del MVP.
- `docs/plan-implantacion.md`: bloques de implantación y progreso.

## Privacidad

Las facturas, XML e imágenes reales no deben subirse al repositorio. El MVP no persiste documentos ni resultados por defecto.
