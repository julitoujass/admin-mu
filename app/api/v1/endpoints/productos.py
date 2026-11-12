from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.common import OkResponse
from app.schemas.productos import (
    LowStockResponse,
    ProductCategoriesUpdate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockAdjustResponse,
    StockMovementListResponse,
    StockUpdate,
    VariantCreate,
    VariantResponse,
    VariantUpdate,
)
from app.services.audit import audit
from app.services.producto_service import ProductService

router = APIRouter()

COST_FIELDS = ("precio_costo",)


def _can_see_costs(user) -> bool:
    return getattr(user, "rol", None) == "admin"


def _without_costs(product: dict) -> dict:
    """Copy of a product row whose variants carry no cost data."""
    variants = [
        {key: value for key, value in variant.items() if key not in COST_FIELDS}
        for variant in product.get("variantes") or []
    ]
    return {**product, "variantes": variants}


@router.get("/", response_model=List[ProductResponse])
def get_products(categoria_id: Optional[int] = None, current_user = Depends(get_current_user)):
    products = ProductService.get_products(categoria_id)
    if _can_see_costs(current_user):
        return products
    return [_without_costs(product) for product in products]

# Declared before any `/{id}` route so "stock-bajo" is never parsed as a product id.
@router.get("/stock-bajo", response_model=LowStockResponse)
def get_low_stock(current_user = Depends(get_current_user)):
    return ProductService.get_low_stock()

@router.put("/{id}/categorias", response_model=ProductResponse)
def set_product_categories(
    id: UUID,
    update: ProductCategoriesUpdate,
    background_tasks: BackgroundTasks,
    current_user = Depends(RoleChecker(["admin"])),
):
    try:
        product = ProductService.set_categories(str(id), update.categoria_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "productos",
        entidad_id=str(id),
        descripcion="Categorías actualizadas",
        payload=update.model_dump(),
        respuesta=product,
    )
    return product

@router.get("/sku/{sku}", response_model=ProductResponse)
def get_product_by_sku(sku: str, current_user = Depends(get_current_user)):
    product = ProductService.get_product_by_sku(sku)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product if _can_see_costs(current_user) else _without_costs(product)

@router.patch("/inventario/stock", response_model=StockAdjustResponse)
def update_stock(update: StockUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.update_stock(update, current_user.id)
    audit(
        background_tasks,
        current_user,
        "ADJUST_STOCK",
        "producto_variantes",
        entidad_id=str(update.variante_id),
        payload=update.model_dump(mode="json"),
        respuesta=result,
    )
    return result

@router.post("/", response_model=ProductResponse)
def create_product(product: ProductCreate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.create_product(product)
    audit(
        background_tasks,
        current_user,
        "CREATE",
        "productos",
        entidad_id=str(result["id"]),
        payload=product.model_dump(),
        respuesta=result,
    )
    return result

@router.post("/variante", response_model=VariantResponse)
def create_variant(variant: VariantCreate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.create_variant(variant)
    audit(
        background_tasks,
        current_user,
        "CREATE",
        "producto_variantes",
        entidad_id=str(result["id"]),
        payload=variant.model_dump(mode="json"),
        respuesta=result,
    )
    return result

@router.get("/variante/{id}/movimientos", response_model=StockMovementListResponse)
def get_variant_stock_movements(
    id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user = Depends(RoleChecker(["admin"])),
):
    return ProductService.get_stock_movements(str(id), limit=limit, offset=offset)

@router.patch("/variante/{id}", response_model=VariantResponse)
def update_variant(id: UUID, variant_update: VariantUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    variant = ProductService.update_variant(str(id), variant_update)
    if not variant:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "producto_variantes",
        entidad_id=str(id),
        payload=variant_update.model_dump(exclude_unset=True),
        respuesta=variant,
    )
    return variant

@router.delete("/variante/{id}", response_model=OkResponse)
def delete_variant(id: UUID, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    try:
        deleted = ProductService.delete_variant(str(id))
        if not deleted:
            raise HTTPException(status_code=404, detail="Variante no encontrada")
        audit(
            background_tasks,
            current_user,
            "DELETE",
            "producto_variantes",
            entidad_id=str(id),
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

@router.patch("/{id}", response_model=ProductResponse)
def update_product(id: UUID, product_update: ProductUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    product = ProductService.update_product(str(id), product_update)
    if not product:
         raise HTTPException(status_code=404, detail="Producto no encontrado")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "productos",
        entidad_id=str(id),
        payload=product_update.model_dump(exclude_unset=True),
        respuesta=product,
    )
    return product

@router.delete("/{id}", response_model=OkResponse)
def delete_product(id: UUID, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    try:
        deleted = ProductService.delete_product(str(id))
        if not deleted:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        audit(
            background_tasks,
            current_user,
            "DELETE",
            "productos",
            entidad_id=str(id),
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
