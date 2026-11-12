from datetime import datetime
from typing import Annotated, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, model_validator

MetodoPago = Literal["Efectivo", "Tarjeta", "QR"]
EstadoVenta = Literal["completada", "anulada"]
MotivoAnulacion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# Amount columns that may be NULL on rows stored before they existed: read them as 0.
Monto = Annotated[float, BeforeValidator(lambda value: 0 if value is None else value)]


class VentaItem(BaseModel):
    variante_id: UUID
    cantidad: int = Field(gt=0, le=1000)
    # Deprecated and IGNORED: accepted only so older clients keep working.
    # Prices and costs are always read from the database by `registrar_venta`.
    precio_unitario: Optional[float] = Field(
        default=None,
        deprecated=True,
        description="Ignorado. El precio se toma siempre de la base de datos.",
    )


class AjusteVenta(BaseModel):
    """Whole-sale discount or surcharge: a percentage (0..100) or a fixed amount."""

    tipo: Literal["porcentaje", "monto"]
    valor: float = Field(ge=0)

    @model_validator(mode="after")
    def _percentage_up_to_100(self):
        if self.tipo == "porcentaje" and self.valor > 100:
            raise ValueError("el porcentaje no puede superar 100")
        return self


class VentaCreate(BaseModel):
    # Unknown fields sent by clients (e.g. `total`) are ignored: the total is computed in the database.
    items: List[VentaItem] = Field(min_length=1, max_length=200)
    metodo_pago: MetodoPago
    cliente_id: Optional[UUID] = None
    # The discount applies to the subtotal; the surcharge to the discounted amount.
    descuento: Optional[AjusteVenta] = None
    recargo: Optional[AjusteVenta] = None


class VentaAnular(BaseModel):
    motivo: MotivoAnulacion


class DevolucionItemCreate(BaseModel):
    variante_id: UUID
    cantidad: int = Field(gt=0, le=1000)


class DevolucionCreate(BaseModel):
    motivo: MotivoAnulacion
    items: List[DevolucionItemCreate] = Field(min_length=1, max_length=200)


class VentaResponse(BaseModel):
    id: UUID
    created_at: datetime
    subtotal: Monto
    descuento_aplicado: Monto
    recargo_aplicado: Monto
    total: float
    metodo_pago: str
    estado: str


class PersonaRef(BaseModel):
    """Embedded `{id, nombre}` of a customer or a user."""

    id: UUID
    nombre: Optional[str] = None


class VentaListItem(VentaResponse):
    cliente: Optional[PersonaRef] = None
    usuario: Optional[PersonaRef] = None
    # Sum of the refunds registered for the sale (0 when it has none).
    total_devuelto: Monto = 0


class VentaListResponse(BaseModel):
    items: List[VentaListItem]
    # Exact number of sales matching the filters, regardless of limit/offset.
    total: int


class VentaDetalleItem(BaseModel):
    variante_id: Optional[UUID] = None
    sku: Optional[str] = None
    producto_nombre: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    cantidad: int
    # Units of this variant already returned (sum over the sale's returns).
    cantidad_devuelta: int = 0
    precio_unitario: float
    subtotal: float


class VentaDetalleItemAdmin(VentaDetalleItem):
    costo_unitario: Monto


class DevolucionItemResponse(BaseModel):
    variante_id: UUID
    cantidad: int
    monto: Monto


class DevolucionResponse(BaseModel):
    id: UUID
    created_at: datetime
    motivo: str
    monto: Monto
    metodo_pago: str
    usuario: Optional[PersonaRef] = None
    items: List[DevolucionItemResponse] = []


class _VentaDetalleBase(VentaListItem):
    motivo_anulacion: Optional[str] = None
    anulada_at: Optional[datetime] = None
    anulada_por: Optional[PersonaRef] = None
    devoluciones: List[DevolucionResponse] = []


# The two detail models are siblings (not parent/child) on purpose: the endpoint
# returns an instance of one of them and the response union must match it exactly.
class VentaDetalleResponse(_VentaDetalleBase):
    """Sale detail without cost data (any role)."""

    items: List[VentaDetalleItem]


class VentaDetalleAdminResponse(_VentaDetalleBase):
    """Sale detail with cost data (admin only)."""

    total_costo: Monto
    items: List[VentaDetalleItemAdmin]
