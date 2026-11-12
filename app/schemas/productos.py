from datetime import datetime
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
    # PATCH /productos/inventario/stock (atomic `registrar_ajuste_stock`) or a sale.
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
    # Cost data is admin-only: the endpoints send `null` to every other role.
    precio_costo: Optional[float] = None
    stock_actual: int = 0
    stock_minimo: int = 0


class StockAdjustResponse(VariantResponse):
    """Full `producto_variantes` row returned by the `registrar_ajuste_stock` function."""

    model_config = ConfigDict(extra="allow")

    tiendanube_variant_id: Optional[str] = None
    updated_at: Optional[str] = None


class ProductCreate(BaseModel):
    nombre: Nombre
    descripcion: Optional[Descripcion] = None
    marca_id: Optional[int] = None


class ProductUpdate(BaseModel):
    nombre: Optional[Nombre] = None
    descripcion: Optional[Descripcion] = None
    marca_id: Optional[int] = None


class CategoriaRef(BaseModel):
    id: int
    nombre: str


class ProductResponse(BaseModel):
    id: UUID4
    nombre: str
    descripcion: Optional[str] = None
    marca_id: Optional[int] = None
    created_at: Optional[datetime] = None
    variantes: List[VariantResponse] = []
    categorias: List[CategoriaRef] = []


class ProductCategoriesUpdate(BaseModel):
    """Replaces the whole set of categories of a product (an empty list clears it)."""

    categoria_ids: List[int] = Field(max_length=50)

    @field_validator("categoria_ids")
    @classmethod
    def _unique_ids(cls, value: List[int]) -> List[int]:
        if len(set(value)) != len(value):
            raise ValueError("categoria_ids no puede tener ids repetidos")
        return value


class LowStockItem(BaseModel):
    """Variant at or below its minimum stock. No cost data."""

    variante_id: UUID
    producto_id: UUID
    producto_nombre: str
    sku: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    stock_actual: int
    stock_minimo: int


class LowStockResponse(BaseModel):
    items: List[LowStockItem]
    total: int


class StockUpdate(BaseModel):
    variante_id: UUID4
    # Delta applied to the current stock: positive adds, negative removes.
    cantidad: int
    # Stored in the stock ledger (`movimientos_stock.motivo`) and in the audit log.
    motivo: Motivo

    @field_validator("cantidad")
    @classmethod
    def _cantidad_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("cantidad no puede ser 0")
        return value


class UsuarioRef(BaseModel):
    # Plain UUID: profile ids come from auth.users and are not necessarily version 4.
    id: UUID
    nombre: Optional[str] = None


class StockMovementResponse(BaseModel):
    """One row of the stock ledger (kardex) of a variant."""

    id: int
    created_at: datetime
    # 'venta' | 'anulacion' | 'ajuste'
    tipo: str
    # Signed delta: negative when stock left, positive when it came back or was added.
    cantidad: int
    stock_resultante: int
    venta_id: Optional[UUID] = None
    motivo: Optional[str] = None
    usuario: Optional[UsuarioRef] = None


class StockMovementListResponse(BaseModel):
    items: List[StockMovementResponse]
    # Exact number of movements of the variant, regardless of limit/offset.
    total: int
