from datetime import date
from typing import Annotated, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.ventas import (
    EstadoVenta,
    MetodoPago,
    VentaAnular,
    VentaCreate,
    VentaDetalleAdminResponse,
    VentaDetalleResponse,
    VentaListResponse,
    VentaResponse,
)
from app.services.audit import audit
from app.services.venta_service import VentaService

router = APIRouter()

IDEMPOTENCY_KEY_MAX_LENGTH = 100
SALE_NOT_FOUND = "Venta no encontrada"


def _is_admin(user) -> bool:
    return getattr(user, "rol", None) == "admin"


def _sale_detail(venta_id: str, include_costs: bool):
    """Sale detail as the response model of the caller's role; 404 when it does not exist."""
    venta = VentaService.get_venta(venta_id, include_costs=include_costs)
    if not venta:
        raise HTTPException(status_code=404, detail=SALE_NOT_FOUND)
    model = VentaDetalleAdminResponse if include_costs else VentaDetalleResponse
    return model.model_validate(venta)


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

    result = VentaService.crear_venta(current_user.id, venta, key, es_admin=_is_admin(current_user))
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


@router.get("/", response_model=VentaListResponse)
def listar_ventas(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    metodo_pago: Optional[MetodoPago] = None,
    estado: Optional[EstadoVenta] = None,
    cliente_id: Optional[UUID] = None,
    usuario_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
):
    return VentaService.listar_ventas(
        desde=desde,
        hasta=hasta,
        metodo_pago=metodo_pago,
        estado=estado,
        cliente_id=str(cliente_id) if cliente_id else None,
        usuario_id=str(usuario_id) if usuario_id else None,
        limit=limit,
        offset=offset,
    )


# Declared before `/{id}` so "hoy" is not parsed as a sale id.
@router.get("/hoy", response_model=List[VentaResponse])
def get_ventas_hoy(current_user=Depends(get_current_user)):
    return VentaService.get_ventas_hoy()


@router.get("/{id}", response_model=Union[VentaDetalleAdminResponse, VentaDetalleResponse])
def get_venta(id: UUID, current_user=Depends(get_current_user)):
    return _sale_detail(str(id), include_costs=_is_admin(current_user))


@router.post("/{id}/anular", response_model=VentaDetalleAdminResponse)
def anular_venta(
    id: UUID,
    datos: VentaAnular,
    background_tasks: BackgroundTasks,
    current_user=Depends(RoleChecker(["admin"])),
):
    result = VentaService.anular_venta(str(id), current_user.id, datos.motivo)
    audit(
        background_tasks,
        current_user,
        "CANCEL_SALE",
        "ventas",
        entidad_id=str(id),
        descripcion=f"Motivo: {datos.motivo}",
        payload=datos.model_dump(),
        respuesta=result,
    )
    return _sale_detail(str(id), include_costs=True)
