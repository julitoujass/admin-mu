from datetime import datetime
from typing import Annotated, Optional

from pydantic import UUID4, BaseModel, EmailStr, Field, StrictBool, StringConstraints


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

class UsuarioCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72, repr=False)
    nombre: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    apellido: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]] = None
    rol_id: int


class UsuarioCreadoResponse(UsuarioResponse):
    email: str


class UsuarioRoleUpdate(BaseModel):
    rol_id: int

class UsuarioActivoUpdate(BaseModel):
    activo: StrictBool

class MeResponse(BaseModel):
    id: str
    email: Optional[str] = None
    rol: str
    activo: bool
