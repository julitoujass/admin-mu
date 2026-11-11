from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.caja import (
    CajaApertura,
    CajaCierre,
    CajaMovimiento,
    CajaMovimientoResponse,
    CajaResumenResponse,
    SesionCajaResponse,
)
from app.services.audit import audit
from app.services.caja_service import CajaService

router = APIRouter()


@router.get("/estado", response_model=Optional[SesionCajaResponse])
def get_estado(current_user=Depends(get_current_user)):
    return CajaService.get_sesion_activa()


@router.get("/resumen", response_model=Optional[CajaResumenResponse])
def get_resumen(current_user=Depends(get_current_user)):
    """Live totals of the open session; `null` when the register is closed."""
    return CajaService.obtener_resumen()


@router.post("/apertura", response_model=SesionCajaResponse)
def abrir_caja(datos: CajaApertura, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    # The session owner is the authenticated user; any `usuario_id` in the body is ignored.
    result = CajaService.abrir_caja(current_user.id, datos)
    audit(
        background_tasks,
        current_user,
        "OPEN_CAJA",
        "sesiones_caja",
        entidad_id=str(result["id"]),
        payload=datos.model_dump(mode="json"),
        respuesta=result,
    )
    return result


@router.post("/movimiento", response_model=CajaMovimientoResponse)
def registrar_movimiento(
    datos: CajaMovimiento, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)
):
    result = CajaService.registrar_movimiento(datos)
    audit(
        background_tasks,
        current_user,
        "CASH_MOVEMENT",
        "movimientos_caja",
        entidad_id=str(result["id"]),
        descripcion=f"{datos.tipo.upper()}: {datos.motivo}",
        payload=datos.model_dump(mode="json"),
        respuesta=result,
    )
    return result


@router.get("/movimientos", response_model=List[CajaMovimientoResponse])
def get_movimientos(current_user=Depends(get_current_user)):
    return CajaService.obtener_movimientos()


@router.post("/cierre", response_model=SesionCajaResponse)
def cerrar_caja(datos: CajaCierre, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    result = CajaService.cerrar_caja(datos)
    audit(
        background_tasks,
        current_user,
        "CLOSE_CAJA",
        "sesiones_caja",
        entidad_id=str(result["id"]),
        payload=datos.model_dump(mode="json"),
        respuesta=result,
    )
    return result


@router.get("/sesiones", response_model=List[SesionCajaResponse])
def get_sesiones(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user=Depends(RoleChecker(["admin"])),
):
    return CajaService.obtener_sesiones(limit, offset)


@router.get("/sesiones/{sesion_id}/movimientos", response_model=List[CajaMovimientoResponse])
def get_movimientos_por_sesion(sesion_id: UUID, current_user=Depends(RoleChecker(["admin"]))):
    return CajaService.obtener_movimientos_por_sesion(str(sesion_id))
