"""Punto de entrada de la API de Lumen.

Ejecutar en desarrollo (desde la carpeta backend, con el entorno virtual activo):
    uvicorn app.main:app --reload --no-access-log
"""

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import BACKEND_DIR, get_settings
from app.routers import (
    agenda, anamnesis, audit_log, report_sections, auth, ayex_form, bps_payments, bps_schedule, cash, clinical, dashboard, degrees, files, goals, guardians, institutions,
    monthly_summary, notices, owner_auth, owner_clinics, owner_export, owner_insights, owner_lifecycle,
    patient_export, patient_import, patients, users,
)
from app.schemas import validation_message

logger = logging.getLogger("medflow")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title="Lumen API",
    version="0.1.0",
    # La documentación interactiva solo se publica en desarrollo.
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

for module in (auth, users, patient_import, patient_export, patients, guardians, institutions, agenda,
               clinical, anamnesis, report_sections, files, goals, audit_log, dashboard, monthly_summary, ayex_form, degrees, bps_schedule, notices,
               owner_auth, owner_clinics, owner_insights, owner_export, owner_lifecycle, cash, bps_payments):
    app.include_router(module.router)


@app.get("/api/health", tags=["sistema"])
def health():
    return {"status": "ok"}


# Política de contenido para la interfaz: solo se cargan archivos del propio servidor.
_APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; object-src 'none'"
)


# ---------- Cabeceras de seguridad y registro técnico mínimo ----------


def _is_file_view(request: Request, response) -> bool:
    return (request.method == "GET" and response.status_code == 200
            and (request.url.path.startswith("/api/files/") or request.url.path.startswith("/api/degrees/"))
            and request.url.path.endswith("/download")
            and request.query_params.get("view") == "true")


@app.middleware("http")
async def security_headers_and_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if path.startswith("/api/docs"):
        pass  # la documentación interactiva (solo desarrollo) usa recursos externos
    elif _is_file_view(request, response):
        # Visor de archivos: el PDF o la imagen se muestra DENTRO de Lumen (mismo origen).
        # Sin otras reglas de contenido: el visor de PDF del navegador las necesita, y el
        # archivo ya se validó al subirlo (solo PDF, PNG o JPG reales).
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    elif path.startswith("/api/"):
        # Datos de salud: el navegador no debe guardar copias en caché.
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    else:
        response.headers["Content-Security-Policy"] = _APP_CSP
        # La interfaz: el navegador debe comprobar siempre si hay una versión nueva
        # (evita que una copia vieja en caché hable con un servidor actualizado).
        response.headers["Cache-Control"] = "no-cache"
    # Registro técnico SIN parámetros de búsqueda (podrían contener nombres) ni cuerpos.
    logger.info(
        "%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


# ---------- Compresión ----------


class _Compression:
    """Comprime las respuestas (gzip) para que carguen más rápido por internet: la interfaz
    pasa de unos 340 KB a menos de 100 KB.

    Las respuestas de inicio de sesión (/api/auth y /api/owner/auth) no se comprimen: llevan el token CSRF y
    así se evita el ataque conocido como BREACH (adivinar secretos midiendo el tamaño
    comprimido). La exportación de una clínica (un .zip, ya comprimido) tampoco."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1000, compresslevel=6)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (path.startswith(("/api/auth", "/api/owner/auth"))
                                        or path.startswith("/api/owner/exports/")):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


app.add_middleware(_Compression)


# ---------- Errores: mensajes claros y sin exponer datos ----------


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Responde en español y SIN repetir lo que se envió (podría ser contenido clínico)."""
    errors = []
    for err in exc.errors():
        message = validation_message(err)
        field = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        errors.append({"field": field, "message": message})
    return JSONResponse(status_code=422, content={"detail": "Revisá los datos ingresados.",
                                                  "errors": errors})


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if exc.status_code == 404 and detail == "Not Found":
        detail = "No encontrado."
    elif exc.status_code == 405:
        detail = "Método no permitido."
    return JSONResponse(status_code=exc.status_code, content={"detail": detail},
                        headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    # En desarrollo se muestra el detalle en la terminal (solo hay datos ficticios).
    # En producción solo el tipo de error: los mensajes de la base pueden incluir datos.
    if settings.is_production:
        logger.error("Error inesperado en %s %s: %s", request.method, request.url.path,
                     type(exc).__name__)
    else:
        logger.exception("Error inesperado en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": "Ocurrió un error inesperado. Intentá nuevamente."})


# ---------- Interfaz web (frontend compilado) ----------
# La API y la interfaz se sirven desde el mismo origen (http://localhost:8000),
# así la cookie de sesión funciona sin abrir CORS.
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

if (FRONTEND_DIST / "index.html").is_file():

    # Pantalla del dueño del sistema: la misma interfaz, que muestra esa sección en /sistema.
    @app.get("/sistema", include_in_schema=False)
    def owner_page():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/sistema/", include_in_schema=False)
    def owner_page_slash():
        return RedirectResponse("/sistema", status_code=308)

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def frontend_missing():
        return (
            "<!doctype html><meta charset='utf-8'><title>Lumen</title>"
            "<p>La API de Lumen está funcionando, pero falta compilar la interfaz.</p>"
            "<p>En otra terminal, dentro de la carpeta <code>frontend</code>, ejecutá "
            "<code>npm install</code> y luego <code>npm run build</code>. "
            "Después detené el backend (Ctrl+C), volvé a iniciarlo y recargá esta página.</p>"
        )
