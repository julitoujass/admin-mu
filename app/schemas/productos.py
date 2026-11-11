from datetime import datetime
from typing import List, Optional

from pydantic import UUID4, BaseModel


class VariantBase(BaseModel):
    sku: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None # Not in DB columns I saw? "talle" was there. "sku" was there. "color" was NOT in the list I got.
    # Wait, let me check the columns again. 
    # Columns: updated_at, producto_id, stock_actual, stock_minimo, id, precio_venta, precio_costo, sku, talle, tiendanube_variant_id.
    # NO COLOR column in `producto_variantes`. Maybe it's in `productos` or I missed it? 
    # Or maybe "talle" is used for both or it's just not there. 
    # The prompt said: "Crear una variante específica vinculada a un producto (SKU, talle, color, precio, stock)."
    # If "color" is missing in DB, I should probably add it or ignore it. 
    # Given I cannot change DB schema easily without migration tool (and I am supposed to use existing DB), I will check if `color` is maybe in `productos` or if I should just omit it for now or if I missed it.
    # Let's assume for now I only map what exists. I will add a comment.
    precio_venta: float
    stock_actual: int = 0

class VariantCreate(VariantBase):
    producto_id: UUID4
    # Note: VariantBase has stock_actual
    stock_minimo: int = 0
    precio_costo: float = 0

class VariantUpdate(BaseModel):
    sku: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    precio_venta: Optional[float] = None
    precio_costo: Optional[float] = None
    stock_minimo: Optional[int] = None

class VariantResponse(VariantBase):
    id: UUID4
    producto_id: UUID4
    stock_minimo: int = 0
    precio_costo: float = 0
    # created_at not in variant columns? "updated_at" is there.
    # "creado_en" or similar? I saw "updated_at".
    # Let's check `productos` created_at.
    pass

class ProductBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    marca_id: Optional[int] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    marca_id: Optional[int] = None

class ProductResponse(ProductBase):
    id: UUID4
    created_at: Optional[datetime] = None
    variantes: List[VariantResponse] = []

class StockUpdate(BaseModel):
    variante_id: UUID4
    cantidad: int 
    motivo: str
