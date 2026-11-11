from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.auth_deps import get_current_user
from app.schemas.ventas import VentaCreate, VentaResponse
from app.services.log_service import LogService
from app.services.venta_service import VentaService

router = APIRouter()

@router.post("/", response_model=VentaResponse)
def crear_venta(venta: VentaCreate, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    result = VentaService.crear_venta(current_user.id, venta)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="CREATE_VENTA",
        entidad="ventas",
        entidad_id=str(result["id"]),
        descripcion=f"Total: ${result['total']}",
        payload_enviado=venta.model_dump(),
        respuesta_recibida=result
    )
    return result

@router.get("/hoy", response_model=List[VentaResponse])
def get_ventas_hoy(current_user = Depends(get_current_user)):
    return VentaService.get_ventas_hoy()
