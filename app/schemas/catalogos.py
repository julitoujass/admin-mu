from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

# ============ MARCAS ============

class MarcaBase(BaseModel):
    nombre: str
    contacto_nombre: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None

class MarcaCreate(MarcaBase):
    pass

class MarcaUpdate(BaseModel):
    nombre: Optional[str] = None
    contacto_nombre: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None

class MarcaResponse(MarcaBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# ============ CATEGORIAS ============

class CategoriaBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    tiendanube_id: Optional[str] = None

class CategoriaCreate(CategoriaBase):
    pass

class CategoriaUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    tiendanube_id: Optional[str] = None

class CategoriaResponse(CategoriaBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
