from fastapi import APIRouter, Depends
from app.schemas.caja import SesionCajaResponse, CajaApertura, CajaMovimiento, CajaCierre, CajaMovimientoResponse
from app.services.caja_service import CajaService
from app.api.auth_deps import get_current_user
from typing import Optional, List

router = APIRouter()

@router.get("/estado", response_model=Optional[SesionCajaResponse])
def get_estado(current_user = Depends(get_current_user)):
    return CajaService.get_sesion_activa(current_user.id)

@router.post("/apertura", response_model=SesionCajaResponse)
def abrir_caja(datos: CajaApertura, current_user = Depends(get_current_user)):
    # Use usuario_id from the request body as requested
    return CajaService.abrir_caja(str(datos.usuario_id), datos)

@router.post("/movimiento")
def registrar_movimiento(datos: CajaMovimiento, current_user = Depends(get_current_user)):
    return CajaService.registrar_movimiento(current_user.id, datos)

@router.get("/movimientos", response_model=List[CajaMovimientoResponse])
def get_movimientos(current_user = Depends(get_current_user)):
    return CajaService.obtener_movimientos(current_user.id)

@router.post("/cierre")
def cerrar_caja(datos: CajaCierre, current_user = Depends(get_current_user)):
    return CajaService.cerrar_caja(current_user.id, datos)
