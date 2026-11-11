from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import UUID4, BaseModel, Field, StringConstraints

Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CajaApertura(BaseModel):
    monto_apertura: float = Field(ge=0)
    # Deprecated and IGNORED: the session owner is always the authenticated user.
    # Accepted only so older clients that still send it keep working.
    usuario_id: Optional[UUID] = Field(
        default=None,
        deprecated=True,
        exclude=True,
        description="Ignorado. El usuario se toma del token.",
    )


class CajaMovimiento(BaseModel):
    tipo: Literal["ingreso", "egreso"]
    monto: float = Field(gt=0)
    motivo: Motivo


class CajaMovimientoResponse(BaseModel):
    model_config = {"populate_by_name": True}

    id: UUID4
    sesion_id: UUID4
    tipo: Literal["ingreso", "egreso"]
    monto: float
    # DB column 'motivo' -> serialized as 'descripcion'
    descripcion: str = Field(validation_alias="motivo")
    # DB column 'creado_en' -> serialized as 'created_at'
    created_at: datetime = Field(validation_alias="creado_en")


class CajaCierre(BaseModel):
    monto_real_efectivo: float = Field(ge=0)
    observaciones: Optional[str] = Field(default=None, max_length=500)


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


class CajaResumenResponse(BaseModel):
    """Live totals of a cash session, computed by the `resumen_caja` database function."""

    sesion_id: UUID
    estado: str
    fecha_apertura: datetime
    monto_apertura: float
    ventas_efectivo: float
    ventas_tarjeta: float
    ventas_qr: float
    cantidad_ventas: int
    ingresos: float
    egresos: float
    # monto_apertura + ventas_efectivo + ingresos - egresos
    esperado_efectivo: float
