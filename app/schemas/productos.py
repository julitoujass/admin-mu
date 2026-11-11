from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import UUID4, BaseModel, Field, StringConstraints, field_validator

# Input constraints. Response models below are deliberately unconstrained so
# rows stored before these limits existed can still be listed.
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Descripcion = Annotated[str, StringConstraints(max_length=1000)]
Sku = Annotated[str, StringConstraints(max_length=64)]
Talle = Annotated[str, StringConstraints(max_length=20)]
Color = Annotated[str, StringConstraints(max_length=40)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class VariantCreate(BaseModel):
    producto_id: UUID4
    sku: Optional[Sku] = None
    talle: Optional[Talle] = None
    color: Optional[Color] = None
    precio_venta: float = Field(ge=0)
    precio_costo: float = Field(default=0, ge=0)
    stock_actual: int = Field(default=0, ge=0)
    stock_minimo: int = Field(default=0, ge=0)


class VariantUpdate(BaseModel):
    # stock_actual is intentionally absent: stock only changes through
    # PATCH /productos/inventario/stock (atomic `ajustar_stock`) or a sale.
    sku: Optional[Sku] = None
    talle: Optional[Talle] = None
    color: Optional[Color] = None
    precio_venta: Optional[float] = Field(default=None, ge=0)
    precio_costo: Optional[float] = Field(default=None, ge=0)
    stock_minimo: Optional[int] = Field(default=None, ge=0)


class VariantResponse(BaseModel):
    id: UUID4
    producto_id: UUID4
    sku: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    precio_venta: float
    precio_costo: float = 0
    stock_actual: int = 0
    stock_minimo: int = 0


class ProductCreate(BaseModel):
    nombre: Nombre
    descripcion: Optional[Descripcion] = None
    marca_id: Optional[int] = None


class ProductUpdate(BaseModel):
    nombre: Optional[Nombre] = None
    descripcion: Optional[Descripcion] = None
    marca_id: Optional[int] = None


class ProductResponse(BaseModel):
    id: UUID4
    nombre: str
    descripcion: Optional[str] = None
    marca_id: Optional[int] = None
    created_at: Optional[datetime] = None
    variantes: List[VariantResponse] = []


class StockUpdate(BaseModel):
    variante_id: UUID4
    # Delta applied to the current stock: positive adds, negative removes.
    cantidad: int
    motivo: Motivo

    @field_validator("cantidad")
    @classmethod
    def _cantidad_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("cantidad no puede ser 0")
        return value
