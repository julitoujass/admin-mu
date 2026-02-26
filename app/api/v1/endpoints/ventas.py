from fastapi import APIRouter, Depends
from app.schemas.ventas import VentaCreate, VentaResponse
from app.services.venta_service import VentaService
from app.api.auth_deps import get_current_user
from typing import List

router = APIRouter()

@router.post("/", response_model=VentaResponse)
def crear_venta(venta: VentaCreate, current_user = Depends(get_current_user)):
    return VentaService.crear_venta(current_user.id, venta)

@router.get("/hoy", response_model=List[VentaResponse])
def get_ventas_hoy(current_user = Depends(get_current_user)):
    return VentaService.get_ventas_hoy()
