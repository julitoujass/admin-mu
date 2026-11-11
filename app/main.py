import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.api.v1.endpoints import caja, catalogos, clientes, productos, reportes, usuarios, ventas
from app.core.config import settings
from app.core.exceptions import CajaError, StockError, UsuarioError
from app.core.supabase import supabase

logging.basicConfig(
    level=logging.getLevelNamesMapping().get(settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

INTERNAL_ERROR_DETAIL = "Error interno del servidor"

# PostgreSQL / PostgREST error code -> (HTTP status, public message)
API_ERROR_MAP = {
    "23505": (409, "Conflicto: el registro ya existe"),
    "23503": (409, "Conflicto: el registro está referenciado por otros datos"),
    "PGRST116": (404, "Recurso no encontrado"),
    "22P02": (400, "Dato inválido"),
    "23514": (400, "Dato fuera de rango"),
}

# Custom codes raised by our own database functions (crear_venta, cerrar_caja, ...).
# Their message is written by us in Spanish, so it is safe to return as `detail`.
DB_BUSINESS_ERROR_STATUS = {
    "MU001": 400,  # no open cash session
    "MU002": 409,  # insufficient stock / stock would go negative
    "MU003": 400,  # invalid input
    "MU004": 404,  # not found
    "MU005": 409,  # cash session already closed
}

app = FastAPI(title="Uniforms POS API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


# Exception Handlers
@app.exception_handler(StockError)
async def stock_exception_handler(request: Request, exc: StockError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )


@app.exception_handler(UsuarioError)
async def usuario_exception_handler(request: Request, exc: UsuarioError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(CajaError)
async def caja_exception_handler(request: Request, exc: CajaError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    if exc.code in DB_BUSINESS_ERROR_STATUS and exc.message:
        # Business rule enforced inside the database: its message is ours.
        status_code, detail = DB_BUSINESS_ERROR_STATUS[exc.code], exc.message
    else:
        # The real database error is only logged; the client gets a fixed message.
        status_code, detail = API_ERROR_MAP.get(exc.code, (500, INTERNAL_ERROR_DETAIL))
    log = logger.error if status_code >= 500 else logger.warning
    log(
        "Database error on %s %s: code=%s message=%s details=%s",
        request.method,
        request.url.path,
        exc.code,
        exc.message,
        exc.details,
    )
    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


# Routers
app.include_router(productos.router, prefix="/api/v1/productos", tags=["Productos"])
app.include_router(caja.router, prefix="/api/v1/caja", tags=["Caja"])
app.include_router(ventas.router, prefix="/api/v1/ventas", tags=["Ventas"])
app.include_router(clientes.router, prefix="/api/v1/clientes", tags=["Clientes"])
app.include_router(reportes.router, prefix="/api/v1/reportes", tags=["Reportes"])
app.include_router(catalogos.router, prefix="/api/v1/catalogos", tags=["Catálogos"])
app.include_router(usuarios.router, prefix="/api/v1/usuarios", tags=["Usuarios"])


@app.get("/")
def root():
    return {"message": "Uniforms POS API is running"}


@app.get("/health", tags=["Health"])
def health():
    """Liveness probe: the process is up. Does not touch the database."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
def health_ready():
    """Readiness probe: the database answers one cheap query."""
    try:
        supabase.table("roles").select("id").limit(1).execute()
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}
