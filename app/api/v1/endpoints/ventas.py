from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from app.api.auth_deps import get_current_user
from app.schemas.ventas import VentaCreate, VentaResponse
from app.services.audit import audit
from app.services.venta_service import VentaService

router = APIRouter()

IDEMPOTENCY_KEY_MAX_LENGTH = 100


@router.post("/", response_model=VentaResponse)
def crear_venta(
    venta: VentaCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    current_user=Depends(get_current_user),
):
    key = (idempotency_key or "").strip() or None
    if key and len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key no puede superar los {IDEMPOTENCY_KEY_MAX_LENGTH} caracteres",
        )

    result = VentaService.crear_venta(current_user.id, venta, key)
    audit(
        background_tasks,
        current_user,
        "CREATE_SALE",
        "ventas",
        entidad_id=str(result["id"]),
        descripcion=f"Total: ${result['total']}",
        payload=venta.model_dump(mode="json"),
        respuesta=result,
    )
    return result


@router.get("/hoy", response_model=List[VentaResponse])
def get_ventas_hoy(current_user=Depends(get_current_user)):
    return VentaService.get_ventas_hoy()
