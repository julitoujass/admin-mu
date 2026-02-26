from pydantic import BaseModel, Field, UUID4
from typing import Optional, Literal, List
from datetime import datetime

class CajaApertura(BaseModel):
    monto_apertura: float
    usuario_id: UUID4

class CajaMovimiento(BaseModel):
    tipo: Literal['ingreso', 'egreso']
    monto: float
    motivo: str

class CajaMovimientoResponse(BaseModel):
    id: UUID4
    sesion_id: UUID4
    tipo: Literal['ingreso', 'egreso']
    monto: float
    descripcion: str = Field(validation_alias='motivo')
    created_at: datetime = Field(validation_alias='creado_en')

    class Config:
        populate_by_name = True

class CajaCierre(BaseModel):
    monto_real_efectivo: float
    observaciones: Optional[str] = None

class SesionCajaResponse(BaseModel):
    id: UUID4
    usuario_id: UUID4
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime] = None
    monto_apertura: float
    monto_esperado_efectivo: Optional[float] = None
    monto_real_efectivo: Optional[float] = None
    estado: str
    observaciones: Optional[str] = None
