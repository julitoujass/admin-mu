from fastapi import APIRouter, Depends, HTTPException
from app.schemas.usuarios import UsuarioResponse, UsuarioRoleUpdate, RoleResponse
from app.services.usuario_service import UsuarioService
from app.api.auth_deps import RoleChecker, get_current_user
from typing import List

router = APIRouter()

# Get current user role info
@router.get("/me")
def get_me(current_user = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "rol": getattr(current_user, "rol", "empleado")
    }

# Only admins can manage users
@router.get("/", response_model=List[UsuarioResponse])
def get_usuarios(current_user = Depends(RoleChecker(["admin"]))):
    return UsuarioService.get_usuarios()

@router.get("/roles", response_model=List[RoleResponse])
def get_roles(current_user = Depends(RoleChecker(["admin"]))):
    return UsuarioService.get_roles()

@router.patch("/{id}/rol", response_model=UsuarioResponse)
def update_rol(id: str, update: UsuarioRoleUpdate, current_user = Depends(RoleChecker(["admin"]))):
    usuario = UsuarioService.update_rol(id, update)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario
