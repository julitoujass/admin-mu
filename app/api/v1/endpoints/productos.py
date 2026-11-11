from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.productos import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockUpdate,
    VariantCreate,
    VariantResponse,
    VariantUpdate,
)
from app.services.log_service import LogService
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

@router.get("/sku/{sku}", response_model=ProductResponse)
def get_product_by_sku(sku: str, current_user = Depends(get_current_user)):
    product = ProductService.get_product_by_sku(sku)
    if not product:
        raise HTTPException(status_code=404, detail="Product with this SKU not found")
    return product if _can_see_costs(current_user) else _without_costs(product)

@router.patch("/inventario/stock")
def update_stock(update: StockUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.update_stock(update)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE_STOCK",
        entidad="producto_variantes",
        entidad_id=str(update.variante_id),
        payload_enviado=update.model_dump(mode="json"),
        respuesta_recibida=result
    )
    return result

@router.post("/", response_model=ProductResponse)
def create_product(product: ProductCreate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.create_product(product)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="CREATE",
        entidad="productos",
        entidad_id=str(result["id"]),
        payload_enviado=product.model_dump(),
        respuesta_recibida=result
    )
    return result

@router.post("/variante", response_model=VariantResponse)
def create_variant(variant: VariantCreate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    result = ProductService.create_variant(variant)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="CREATE",
        entidad="producto_variantes",
        entidad_id=str(result["id"]),
        payload_enviado=variant.model_dump(mode="json"),
        respuesta_recibida=result
    )
    return result

@router.patch("/variante/{id}", response_model=VariantResponse)
def update_variant(id: UUID, variant_update: VariantUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    variant = ProductService.update_variant(str(id), variant_update)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE",
        entidad="producto_variantes",
        entidad_id=str(id),
        payload_enviado=variant_update.model_dump(exclude_unset=True),
        respuesta_recibida=variant
    )
    return variant

@router.delete("/variante/{id}")
def delete_variant(id: UUID, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    try:
        deleted = ProductService.delete_variant(str(id))
        if not deleted:
            raise HTTPException(status_code=404, detail="Variant not found")
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="DELETE",
            entidad="producto_variantes",
            entidad_id=str(id)
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

@router.patch("/{id}", response_model=ProductResponse)
def update_product(id: UUID, product_update: ProductUpdate, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    product = ProductService.update_product(str(id), product_update)
    if not product:
         raise HTTPException(status_code=404, detail="Product not found")
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE",
        entidad="productos",
        entidad_id=str(id),
        payload_enviado=product_update.model_dump(exclude_unset=True),
        respuesta_recibida=product
    )
    return product

@router.delete("/{id}")
def delete_product(id: UUID, background_tasks: BackgroundTasks, current_user = Depends(RoleChecker(["admin"]))):
    try:
        deleted = ProductService.delete_product(str(id))
        if not deleted:
            raise HTTPException(status_code=404, detail="Product not found")
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="DELETE",
            entidad="productos",
            entidad_id=str(id)
        )
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
