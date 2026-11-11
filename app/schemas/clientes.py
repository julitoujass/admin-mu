from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import UUID4, BaseModel, EmailStr, StringConstraints, field_validator

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
DniCuit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
Telefono = Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)]
Direccion = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Ciudad = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
TipoIva = Literal["Consumidor Final", "Monotributista", "Responsable Inscripto", "Exento"]

_OPTIONAL_TEXT_FIELDS = ("dni_cuit", "email", "telefono", "direccion", "ciudad", "tipo_iva")


class _ClienteInput(BaseModel):
    """Shared input rules. Blank optional strings become None (stored as NULL)."""

    dni_cuit: Optional[DniCuit] = None
    email: Optional[EmailStr] = None
    telefono: Optional[Telefono] = None
    direccion: Optional[Direccion] = None
    ciudad: Optional[Ciudad] = None
    tipo_iva: Optional[TipoIva] = None

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ClienteCreate(_ClienteInput):
    nombre: Nombre


class ClienteUpdate(_ClienteInput):
    nombre: Optional[Nombre] = None


class ClienteResponse(BaseModel):
    # Unconstrained on purpose: rows stored before input validation existed must still be listed.
    id: UUID4
    nombre: str
    dni_cuit: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    tipo_iva: Optional[str] = None
    created_at: datetime
