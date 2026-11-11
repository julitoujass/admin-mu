from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

MetodoPago = Literal["Efectivo", "Tarjeta", "QR"]


class VentaItem(BaseModel):
    variante_id: UUID
    cantidad: int = Field(gt=0, le=1000)
    # Deprecated and IGNORED: accepted only so older clients keep working.
    # Prices and costs are always read from the database by `crear_venta`.
    precio_unitario: Optional[float] = Field(
        default=None,
        deprecated=True,
        description="Ignorado. El precio se toma siempre de la base de datos.",
    )


class VentaCreate(BaseModel):
    # Unknown fields sent by clients (e.g. `total`) are ignored: the total is computed in the database.
    items: List[VentaItem] = Field(min_length=1, max_length=200)
    metodo_pago: MetodoPago
    cliente_id: Optional[UUID] = None


class VentaResponse(BaseModel):
    id: UUID
    created_at: datetime
    total: float
    metodo_pago: str
