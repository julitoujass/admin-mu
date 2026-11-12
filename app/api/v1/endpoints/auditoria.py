from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth_deps import RoleChecker
from app.schemas.auditoria import AuditLogListResponse
from app.services.auditoria_service import AuditoriaService

router = APIRouter()


@router.get("/", response_model=AuditLogListResponse)
def listar_auditoria(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    evento: Optional[str] = Query(default=None, max_length=64),
    entidad: Optional[str] = Query(default=None, max_length=64),
    usuario_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(RoleChecker(["admin"])),
):
    return AuditoriaService.listar(
        desde=desde,
        hasta=hasta,
        evento=evento,
        entidad=entidad,
        usuario_id=str(usuario_id) if usuario_id else None,
        limit=limit,
        offset=offset,
    )
