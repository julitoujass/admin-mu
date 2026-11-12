from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator, model_validator

from app.schemas.ventas import PersonaRef

NombreNegocio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Cuit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
Direccion = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Telefono = Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)]
PieTicket = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]

OPTIONAL_TEXT_FIELDS = ("cuit", "direccion", "telefono", "pie_ticket")
REQUIRED_FIELDS = ("nombre_negocio", "descuento_max_empleado")


class ConfiguracionUpdate(BaseModel):
    """Partial update: only the fields that are sent change. Optional texts accept `null` to clear them."""

    nombre_negocio: Optional[NombreNegocio] = None
    cuit: Optional[Cuit] = None
    direccion: Optional[Direccion] = None
    telefono: Optional[Telefono] = None
    email: Optional[EmailStr] = None
    pie_ticket: Optional[PieTicket] = None
    descuento_max_empleado: Optional[float] = Field(default=None, ge=0, le=100)

    @field_validator(*OPTIONAL_TEXT_FIELDS, mode="after")
    @classmethod
    def _blank_is_null(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @model_validator(mode="after")
    def _check_sent_fields(self):
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Enviá al menos un campo para actualizar")
        for name in REQUIRED_FIELDS:
            if name in sent and getattr(self, name) is None:
                raise ValueError(f"{name} no puede ser null")
        return self


class ConfiguracionResponse(BaseModel):
    id: int
    nombre_negocio: str
    cuit: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    pie_ticket: Optional[str] = None
    descuento_max_empleado: float
    updated_at: Optional[datetime] = None
    updated_by: Optional[PersonaRef] = None
