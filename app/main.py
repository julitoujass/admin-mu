from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.v1.endpoints import productos, caja, ventas, clientes, reportes, catalogos, usuarios
from app.core.exceptions import StockError, CajaError

app = FastAPI(title="Uniforms POS API", version="1.0.0")

# Exception Handlers
@app.exception_handler(StockError)
async def stock_exception_handler(request: Request, exc: StockError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )

@app.exception_handler(CajaError)
async def caja_exception_handler(request: Request, exc: CajaError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )

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
