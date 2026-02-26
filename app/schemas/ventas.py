from pydantic import BaseModel, UUID4
from typing import List, Optional
from datetime import datetime

class VentaItem(BaseModel):
    variante_id: UUID4
    cantidad: int
    precio_unitario: float

class VentaCreate(BaseModel):
    items: List[VentaItem]
    metodo_pago: str
    cliente_id: Optional[UUID4] = None

class VentaResponse(BaseModel):
    id: UUID4
    created_at: datetime
    total: float
    metodo_pago: str
    # items: List[VentaItem] # Optional to include details in response
