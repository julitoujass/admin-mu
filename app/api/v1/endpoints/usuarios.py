from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.auth_deps import RoleChecker, get_current_user, invalidate_user
from app.schemas.usuarios import (
    MeResponse,
    RoleResponse,
    UsuarioActivoUpdate,
    UsuarioResponse,
    UsuarioRoleUpdate,
)
from app.services.log_service import LogService
from app.services.usuario_service import UsuarioService

router = APIRouter()

# Get current user role info
@router.get("/me", response_model=MeResponse)
def get_me(current_user = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "rol": getattr(current_user, "rol", "empleado"),
        "activo": getattr(current_user, "activo", True),
    }

# Only admins can manage users
@router.get("/", response_model=List[UsuarioResponse])
def get_usuarios(current_user = Depends(RoleChecker(["admin"]))):
    return UsuarioService.get_usuarios()

@router.get("/roles", response_model=List[RoleResponse])
def get_roles(current_user = Depends(RoleChecker(["admin"]))):
    return UsuarioService.get_roles()

@router.patch("/{id}/rol", response_model=UsuarioResponse)
def update_rol(
    id: UUID,
    update: UsuarioRoleUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(RoleChecker(["admin"])),
):
    usuario = UsuarioService.update_rol(str(id), update.rol_id, current_user.id)
    # The cached session still carries the old role: drop it so the change applies now.
    invalidate_user(id)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE_ROL",
        entidad="perfiles",
        entidad_id=str(id),
        payload_enviado=update.model_dump(),
        respuesta_recibida=usuario,
    )
    return usuario

@router.patch("/{id}/activo", response_model=UsuarioResponse)
def update_activo(
    id: UUID,
    update: UsuarioActivoUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(RoleChecker(["admin"])),
):
    usuario = UsuarioService.set_activo(str(id), update.activo, current_user.id)
    invalidate_user(id)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE_ACTIVO",
        entidad="perfiles",
        entidad_id=str(id),
        payload_enviado=update.model_dump(),
        respuesta_recibida=usuario,
    )
    return usuario
