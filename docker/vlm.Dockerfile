# =============================================================================
# VLM local — Qwen2.5-VL para casos complejos
# =============================================================================
# Este servicio es OPCIONAL y está DESACTIVADO por defecto.
#
# Activación:
#   docker compose --profile vlm up
#
# Requisitos:
#   - GPU NVIDIA con soporte CUDA (se valida con --gpus all)
#   - ~15 GB de espacio en disco para modelos
#   - vLLM como servidor de inferencia
#
# Decisión de diseño: el VLM no se activa en producción por defecto.
# Se ofrece como perfil opcional para fases futuras (B9) donde se necesite.
# =============================================================================

FROM nvidia/cuda:12.4-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHON_VERSION=3.10

# Instalar Python y dependencias del sistema para vLLM
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-venv \
    python3.10-dev \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# =============================================================================
# Etapa 1: builder con vLLM + Qwen2.5-VL
# =============================================================================
FROM base AS builder

RUN pip install --no-cache-dir vllm>=0.8.0

# =============================================================================
# Etapa 2: imagen de producción VLM
# =============================================================================
FROM base

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Modelo por defecto — se descarga en la primera ejecución
# El usuario debe换上 su modelo preferido o descargar Qwen2.5-VL explícitamente.
ENV VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
ENV VLLM_HOST=0.0.0.0
ENV VLLM_PORT=8001
ENV VLLM_TENSOR_PARALLEL_SIZE=1
# Cuantas GPUs usar para tensor parallel (1 = una sola GPU, 2 = dos GPUs, etc.)
ENV VLLM_GPU_MEMORY_UTILIZATION=0.85

EXPOSE 8001

# Saludcheck: vLLM levanta en puerto 8001
HEALTHCHECK --interval=30s --timeout=20s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

CMD ["python", "-m", "vllm", "serve", "${VLLM_MODEL}", \
     "--host", "${VLLM_HOST}", \
     "--port", "${VLLM_PORT}", \
     "--tensor-parallel-size", "${VLLM_TENSOR_PARALLEL_SIZE}", \
     "--gpu-memory-utilization", "${VLLM_GPU_MEMORY_UTILIZATION}"]