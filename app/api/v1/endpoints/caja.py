from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.auth_deps import get_current_user
from app.schemas.caja import CajaApertura, CajaCierre, CajaMovimiento, CajaMovimientoResponse, SesionCajaResponse
from app.services.caja_service import CajaService
from app.services.log_service import LogService

router = APIRouter()

@router.get("/estado", response_model=Optional[SesionCajaResponse])
def get_estado(current_user = Depends(get_current_user)):
    return CajaService.get_sesion_activa(current_user.id)

@router.post("/apertura", response_model=SesionCajaResponse)
def abrir_caja(datos: CajaApertura, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    # Use usuario_id from the request body as requested
    result = CajaService.abrir_caja(str(datos.usuario_id), datos)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="APERTURA_CAJA",
        entidad="sesiones_caja",
        entidad_id=str(result.id),
        payload_enviado=datos.model_dump(),
        respuesta_recibida=result.model_dump()
    )
    return result

@router.post("/movimiento")
def registrar_movimiento(datos: CajaMovimiento, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    result = CajaService.registrar_movimiento(current_user.id, datos)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="MOVIMIENTO_CAJA",
        entidad="movimientos_caja",
        entidad_id=str(result["id"]),
        descripcion=f"{datos.tipo.upper()}: {datos.motivo}",
        payload_enviado=datos.model_dump(),
        respuesta_recibida=result
    )
    return result

@router.get("/movimientos", response_model=List[CajaMovimientoResponse])
def get_movimientos(current_user = Depends(get_current_user)):
    return CajaService.obtener_movimientos(current_user.id)

@router.post("/cierre")
def cerrar_caja(datos: CajaCierre, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    result = CajaService.cerrar_caja(current_user.id, datos)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="CIERRE_CAJA",
        entidad="sesiones_caja",
        entidad_id=str(result.get("id", "")),
        payload_enviado=datos.model_dump(),
        respuesta_recibida=result
    )
    return result

@router.get("/sesiones", response_model=List[SesionCajaResponse])
def get_sesiones(current_user = Depends(get_current_user)):
    return CajaService.obtener_sesiones()

@router.get("/sesiones/{sesion_id}/movimientos", response_model=List[CajaMovimientoResponse])
def get_movimientos_por_sesion(sesion_id: str, current_user = Depends(get_current_user)):
    return CajaService.obtener_movimientos_por_sesion(sesion_id)
