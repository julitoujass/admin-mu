from datetime import datetime
from typing import Optional

from pydantic import UUID4, BaseModel


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
