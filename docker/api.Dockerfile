# Etapa 1: builder minimal para dependencias
FROM python:3.10-slim AS builder

WORKDIR /app

# Instalar solo dependencias del sistema necesarias para PyMuPDF y Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    libmupdf1 \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python con wheels precompilados
COPY pyproject.toml .
RUN pip install --no-cache-dir --user -e .


# Etapa 2: imagen de producción
FROM python:3.10-slim

WORKDIR /app

# Dependencias de sistema runtime para PDF y renderizado
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    libmupdf1 \
    libjpeg-dev \
    zlib1g-dev \
    libffi7 \
    && rm -rf /var/lib/apt/lists/*

# Copiar Python packages instalados del builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copiar código de la aplicación
COPY app/ app/
COPY docs/ /dev/null  # excluidos del exclude en pyproject.toml, se copian vacío o se ignoran

# No copiar tests, scripts ni docs al contenedor de producción
# El exclude en pyproject.toml ya filtra estos directorios del package

# Variables de entorno con valores por defecto seguros para producción
ENV APP_ENV=production
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV STORE_INPUT_FILES=false
ENV STORE_EXTRACTION_RESULTS=false
ENV INCLUDE_DEBUG_ARTIFACTS=false

# Exponer puerto API
EXPOSE 8000

# Saludcheck básico
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Ejecutar con uvicorn en modo producción
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]