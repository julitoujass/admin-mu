from pydantic import BaseModel, UUID4
from typing import Optional
from datetime import datetime

class ClienteBase(BaseModel):
    nombre: str
    dni_cuit: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    tipo_iva: Optional[str] = None

class ClienteCreate(ClienteBase):
    pass

class ClienteUpdate(BaseModel):
    nombre: Optional[str] = None
    dni_cuit: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    tipo_iva: Optional[str] = None

class ClienteResponse(ClienteBase):
    id: UUID4
    created_at: datetime
