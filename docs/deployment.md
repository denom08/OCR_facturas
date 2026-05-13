# Despliegue local — OCR Facturas

Este documento describe cómo ejecutar el proyecto con Docker y docker-compose, los requisitos de hardware y las decisiones de diseño para el despliegue.

## Índice

- [Arquitectura de contenedores](#arquitectura-de-contenedores)
- [Servicios disponibles](#servicios-disponibles)
- [Requisitos de hardware](#requisitos-de-hardware)
- [Arranque rápido](#arranque-rápido)
- [Configuración](#configuración)
- [Decisiones de privacidad y persistencia](#decisiones-de-privacidad-y-persistencia)
- [Perfiles opcionales](#perfiles-opcionales)
- [Desarrollo local sin Docker](#desarrollo-local-sin-docker)

---

## Arquitectura de contenedores

```
┌─────────────────────────────────────────────────────────┐
│                      docker-compose                     │
│                                                         │
│  ┌──────────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │     api      │  │   vlm     │  │      redis       │ │
│  │  (FastAPI)   │  │ (Qwen-VL) │  │   (opcional)     │ │
│  │   puerto     │  │   puerto  │  │     puerto       │ │
│  │    8000      │  │   8001    │  │     6379         │ │
│  │              │  │  (GPU)    │  │                  │ │
│  └──────────────┘  └───────────┘  └──────────────────┘ │
│        │                │                 │             │
│  Sin persistencia   Opcional/futuro   Opcional/futuro  │
│  por defecto                                     │
└─────────────────────────────────────────────────┘
```

- **api**: Servicio principal de la API FastAPI. Es el único activo por defecto.
- **vlm**: Modelo visual local (Qwen2.5-VL). Solo para fases con B9. Requiere GPU.
- **redis**: Broker para procesamiento asíncrono futuro (B12). Opcional.

---

## Servicios disponibles

### Servicio `api` (activo por defecto)

| Aspecto | Detalle |
|---|---|
| Imagen base | `python:3.10-slim` |
| Dockerfile | `docker/api.Dockerfile` |
| Puerto | `8000` (configurable vía `APP_PORT`) |
| Persistencia | **Ninguna** — temporales en `tmpfs`, sin volúmenes nombrados |
| Healthcheck | `GET /health` cada 30s |

### Servicio `vlm` (perfil `vlm`)

| Aspecto | Detalle |
|---|---|
| Imagen base | `nvidia/cuda:12.4-runtime-ubuntu22.04` |
| Dockerfile | `docker/vlm.Dockerfile` |
| Puerto | `8001` |
| Requisito | GPU NVIDIA con soporte CUDA |
| Modelo por defecto | `Qwen/Qwen2.5-VL-7B-Instruct` |
| Descarga | Automática en primera ejecución (~15 GB) |

### Servicio `redis` (perfil `redis`)

| Aspecto | Detalle |
|---|---|
| Imagen | `redis:7-alpine` |
| Puerto | `6379` |
| Persistencia | Desactivada (`--appendonly no`) |
| Uso previsto | Broker RQ/Celery para B12 (asincronía) |

---

## Requisitos de hardware

### Para ejecutar la API sin VLM

| Recurso | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 núcleos | 4+ núcleos |
| RAM | 512 MB | 2 GB |
| Disco | 200 MB | 500 MB |
| GPU | No necesaria | — |

La API solo requiere PyMuPDF y Pillow (CPU). Sin OCR ni VLM, el consumo es muy bajo.

### Para activar el servicio VLM (`vlm`)

| Recurso | Mínimo | Recomendado |
|---|---|---|
| GPU | NVIDIA con CUDA 12.4+ | RTX 5070 Ti o RTX 5090 |
| VRAM | 12 GB | 16+ GB |
| RAM | 8 GB | 16 GB |
| Disco | 15 GB (modelo) | 20 GB+ |
| Modelo | Qwen2.5-VL-7B-Instruct (~7B params) | Qwen2.5-VL-14B-Instruct (~14B) |

> **Nota**: el MVP no activa VLM en producción. El servicio `vlm` es un perfil opcional para fases futuras (B9).

---

## Arranque rápido

### 1. Construir y ejecutar la API

```bash
docker compose up --build
```

La API estará disponible en `http://localhost:8000`.

### 2. Verificar que funciona

```bash
curl http://localhost:8000/health
```

Respuesta esperada:

```json
{"status":"ok"}
```

### 3. Extraer una factura

```bash
curl -X POST http://localhost:8000/api/v1/invoices/extract \
  -F "file=@factura.pdf" \
  -F "include_evidence=true"
```

### 4. Activar servicios opcionales

```bash
# Con VLM (requiere GPU NVIDIA)
docker compose --profile vlm up --build

# Con Redis (para asincronía futura)
docker compose --profile redis up

# Con ambos
docker compose --profile vlm --profile redis up
```

---

## Configuración

### Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `APP_ENV` | `production` | Entorno (`production`, `local`) |
| `APP_HOST` | `0.0.0.0` | Host de escucha |
| `APP_PORT` | `8000` | Puerto de la API |
| `STORE_INPUT_FILES` | `false` | Persistir PDFs recibidos (desactivado por defecto) |
| `STORE_EXTRACTION_RESULTS` | `false` | Persistir resultados extraídos (desactivado por defecto) |
| `INCLUDE_DEBUG_ARTIFACTS` | `false` | Guardar artefactos de debug (desactivado por defecto) |
| `VLLM_MODEL` | `Qwen/Qwen2.5-VL-7B-Instruct` | Modelo VLM a cargar |
| `VLLM_PORT` | `8001` | Puerto del servicio VLM |

### Fichero `.env`

Copiar `.env.example` a `.env` para desarrollo local:

```bash
cp .env.example .env
```

> **No subir nunca un `.env` con valores reales a git.**

---

## Decisiones de privacidad y persistencia

### Principio base

> Por defecto, **no se persisten facturas, resultados ni artefactos de debug**.

### Justificación

El proyecto está diseñado para preservar la privacidad de datos fiscales. Las facturas contienen información sensible (CIF/NIF, razones sociales, importes). Persistir estos datos en disco del host o del contenedor introduce riesgos innecesarios.

### Decisiones implementadas

| Decisión | Implementación |
|---|---|
| Sin persistencia de PDFs recibidos | `STORE_INPUT_FILES=false` (por defecto) |
| Sin persistencia de resultados | `STORE_EXTRACTION_RESULTS=false` (por defecto) |
| Sin artefactos de debug | `INCLUDE_DEBUG_ARTIFACTS=false` (por defecto) |
| Temporales efímeros | `tmpfs: /tmp` en contenedor API — nada en disco tras reinicio |
| Sin volúmenes para la API | La API no tiene volúmenes de datos propios |
| Redis efímero | `redis-server --appendonly no` — sin AOF, sin persistencia en disco |

### Excepciones controladas

Si un usuario necesita persistencia temporal:

```bash
# Crear volumen explícito para debugging (no recomendado para producción)
docker compose -f docker-compose.yml up -d

# Montar volumen fuera de docker-compose para auditoría puntual
docker run -v /tmp/invoice-debug:/tmp/invoice-debug ...
```

Esto requiere activación explícita (`STORE_*=true`), nunca por defecto.

---

## Perfiles opcionales

docker-compose usa `--profile` para activar servicios según necesidad:

| Perfil | Servicio | Cuándo usarlo |
|---|---|---|
| `default` | `api` | Uso estándar de la API |
| `vlm` | `vlm` | Fases con B9 (VLM local integrado) |
| `redis` | `redis` | Fases con B12 (asincronía con RQ/Celery) |

### Activar perfil en desarrollo

Añaadir al `.env`:

```env
COMPOSE_PROFILES=vlm
```

O ejecutar directamente:

```bash
docker compose --profile vlm up
```

---

## Desarrollo local sin Docker

Para desarrollo sin Docker, seguir el README principal:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
uvicorn app.api.main:app --reload
```

Los tests también pueden ejecutarse sin Docker:

```bash
pytest
ruff check .
```

---

## Decisión de diseño:为什么不 persistir facturas por defecto

1. **Privacidad fiscal**: CIF/NIF, razones sociales e importes son datos sensibles.
2. **Simplicidad operativa**: sin persistencia, no hay que gestionar GDPR, retención ni limpieza de datos.
3. **Seguridad**: menos superficie de ataque si el contenedor o el host se ven comprometidos.
4. **Arquitectura auditable**: el flujo es `PDF → procesamiento en memoria → JSON`; cada request es independiente.

Si en el futuro se necesita persistencia (auditoría, histórico), se implementará con:
- Volúmenes explícitos activados con flags (`STORE_*=true`)
- Opciones de cifrado en reposo
- Políticas de retención configurables