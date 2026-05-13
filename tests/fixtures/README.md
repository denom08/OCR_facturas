# Tests Fixtures — Política de privacidad

Este directorio contiene fixtures sintéticas para tests y evaluación.

## Estructura

- `digital/` — PDFs digitales sintéticos (no versionados)
- `hybrid/` — PDFs híbridos sintéticos (no versionados)
- `scanned/` — PDFs escaneados sintéticos (no versionados)
- `expected_json/` — Ground truth JSON sintético

## Política

NO guardar facturas reales, imágenes reales ni datos sensibles en git.

Los archivos `expected_json/*.json` son datos seguros sintéticos que SÍ se versionan porque no contienen información real.

Si necesitas añadir PDFs de verdad para evaluación local:
1. No los subas a git
2. Añúdelos a `.gitignore`
3. Usa la variable `FIXTURES_PATH` o similar para referenciarlos localmente

Los ground truths sintéticos permiten:
- Tests reproducibles sin datos sensibles
- Evaluación automatizada del pipeline
- Validación de métricas por campo