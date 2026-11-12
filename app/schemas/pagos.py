from datetime import datetime
from typing import Annotated, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

from app.schemas.ventas import VentaCreate

MetodoPagoTerminal = Literal["Tarjeta", "QR"]
EstadoPago = Literal[
    "pendiente",
    "enviado",
    "aprobado",
    "rechazado",
    "cancelado",
    "indeterminado",
    "venta_registrada",
    "error_registro",
    "reembolsado",
]
DeviceText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]


class CobroTerminalCreate(VentaCreate):
    """Same cart as `POST /ventas/`; only the methods a terminal can charge."""

    metodo_pago: MetodoPagoTerminal


class CobroIniciadoResponse(BaseModel):
    pago_id: UUID
    # Amount being charged, computed by the database (`cotizar_venta`).
    total: float
    estado: EstadoPago


class PagoResponse(BaseModel):
    """What the POS polls while the customer pays."""

    id: UUID
    estado: EstadoPago
    metodo_pago: MetodoPagoTerminal
    monto: float
    # Set once the sale is registered (`estado = venta_registrada`).
    venta_id: Optional[UUID] = None
    tarjeta_marca: Optional[str] = None
    tarjeta_ultimos4: Optional[str] = None
    codigo_autorizacion: Optional[str] = None
    cuotas: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PagoAdminResponse(PagoResponse):
    """Charge as shown in the admin review list."""

    proveedor: str
    external_payment_id: str
    usuario_id: Optional[UUID] = None
    intentos_conciliacion: int = 0


class PagoListResponse(BaseModel):
    items: List[PagoAdminResponse]
    # Exact number of charges matching the filter, regardless of limit/offset.
    total: int


class TerminalIntegracionResponse(BaseModel):
    proveedor: str
    habilitado: bool
    # Result of a quick ping to the device.
    conectado: bool
    # Device details are only filled in for admins.
    device_id: Optional[str] = None
    pos_id: Optional[str] = None
    updated_at: Optional[datetime] = None


class TerminalIntegracionUpdate(BaseModel):
    """Partial update: only the fields that are sent change. Blank texts clear the value."""

    habilitado: Optional[bool] = None
    device_id: Optional[DeviceText] = None
    pos_id: Optional[DeviceText] = None

    @field_validator("device_id", "pos_id", mode="after")
    @classmethod
    def _blank_is_null(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @model_validator(mode="after")
    def _check_sent_fields(self):
        sent = self.model_fields_set
        if not sent:
            raise ValueError("Enviá al menos un campo para actualizar")
        if "habilitado" in sent and self.habilitado is None:
            raise ValueError("habilitado no puede ser null")
        return self
