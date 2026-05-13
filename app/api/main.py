from fastapi import FastAPI

from app.api.routes.invoices import router as invoices_router

app = FastAPI(
    title="OCR Facturas API",
    description="API local para extracción auditable de datos de facturas PDF.",
    version="0.1.0",
)

app.include_router(invoices_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Comprueba que la aplicación arranca correctamente."""
    return {"status": "ok"}
