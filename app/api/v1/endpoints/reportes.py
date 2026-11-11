from fastapi import APIRouter, Depends, Query
from app.api.auth_deps import get_current_user, RoleChecker
from app.services.reporte_service import ReporteService
from app.schemas.reportes import VentasTotalesReporte, ProductoTopReporte, CajaResumenReporte
from typing import List, Optional
from datetime import date

router = APIRouter()

@router.get("/ventas", response_model=VentasTotalesReporte)
def obtener_reporte_ventas(
    fecha_inicio: Optional[date] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    fecha_fin: Optional[date] = Query(None, description="Fecha fin YYYY-MM-DD"),
    current_user = Depends(RoleChecker(["admin"]))
):
    return ReporteService.obtener_ventas_por_rango(fecha_inicio, fecha_fin)

@router.get("/productos-top", response_model=List[ProductoTopReporte])
def obtener_reporte_productos_top(
    fecha_inicio: Optional[date] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    fecha_fin: Optional[date] = Query(None, description="Fecha fin YYYY-MM-DD"),
    current_user = Depends(RoleChecker(["admin"]))
):
    return ReporteService.obtener_top_productos(fecha_inicio, fecha_fin)

@router.get("/cajas", response_model=CajaResumenReporte)
def obtener_reporte_cajas(
    fecha_inicio: Optional[date] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    fecha_fin: Optional[date] = Query(None, description="Fecha fin YYYY-MM-DD"),
    current_user = Depends(RoleChecker(["admin"]))
):
    return ReporteService.obtener_resumen_cajas(fecha_inicio, fecha_fin)
