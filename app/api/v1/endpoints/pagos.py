from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.auth_deps import RoleChecker, get_current_user
from app.api.deps import get_pago_service
from app.schemas.pagos import (
    CobroIniciadoResponse,
    CobroTerminalCreate,
    EstadoPago,
    PagoAdminResponse,
    PagoListResponse,
    PagoResponse,
    TerminalIntegracionResponse,
    TerminalIntegracionUpdate,
)
from app.services.pago_service import PagoService

router = APIRouter()
integraciones_router = APIRouter()


@router.post("/terminal", response_model=CobroIniciadoResponse, status_code=202)
def iniciar_cobro(
    cobro: CobroTerminalCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    service: PagoService = Depends(get_pago_service),
):
    """Start a card / QR charge. The charge runs after the response; poll `GET /pagos/{id}`."""
    return service.iniciar_cobro(cobro, current_user, schedule=background_tasks.add_task)


@router.get("/", response_model=PagoListResponse)
def listar_pagos(
    estado: Optional[EstadoPago] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(RoleChecker(["admin"])),
    service: PagoService = Depends(get_pago_service),
):
    return service.listar(estado=estado, limit=limit, offset=offset)


@router.get("/{id}", response_model=PagoResponse)
def get_pago(
    id: UUID,
    current_user=Depends(get_current_user),
    service: PagoService = Depends(get_pago_service),
):
    return service.get_pago(str(id), current_user)


@router.post("/{id}/cancelar", response_model=PagoResponse)
def cancelar_pago(
    id: UUID,
    current_user=Depends(get_current_user),
    service: PagoService = Depends(get_pago_service),
):
    return service.cancelar(str(id), current_user)


@router.post("/{id}/conciliar", response_model=PagoAdminResponse)
def conciliar_pago(
    id: UUID,
    current_user=Depends(RoleChecker(["admin"])),
    service: PagoService = Depends(get_pago_service),
):
    return service.conciliar_pago(str(id))


@integraciones_router.get("/terminal", response_model=TerminalIntegracionResponse)
def get_integracion_terminal(
    current_user=Depends(get_current_user),
    service: PagoService = Depends(get_pago_service),
):
    estado = service.estado_integracion()
    if getattr(current_user, "rol", None) != "admin":
        # Device details are configuration: only admins see them.
        estado = {**estado, "device_id": None, "pos_id": None, "updated_at": None}
    return estado


@integraciones_router.patch("/terminal", response_model=TerminalIntegracionResponse)
def update_integracion_terminal(
    update: TerminalIntegracionUpdate,
    current_user=Depends(RoleChecker(["admin"])),
    service: PagoService = Depends(get_pago_service),
):
    return service.actualizar_integracion(update.model_dump(exclude_unset=True), current_user)
