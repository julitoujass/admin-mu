from datetime import datetime
from typing import Optional

from pydantic import UUID4, BaseModel, StrictBool


class RoleResponse(BaseModel):
    id: int
    nombre: str

class UsuarioResponse(BaseModel):
    id: UUID4
    nombre: str
    apellido: Optional[str] = None
    activo: bool
    roles: Optional[RoleResponse] = None
    created_at: datetime

class UsuarioRoleUpdate(BaseModel):
    rol_id: int

class UsuarioActivoUpdate(BaseModel):
    activo: StrictBool

class MeResponse(BaseModel):
    id: str
    email: Optional[str] = None
    rol: str
    activo: bool
