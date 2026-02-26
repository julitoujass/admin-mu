from fastapi import APIRouter, Depends, HTTPException
from app.schemas.productos import ProductResponse, ProductCreate, VariantCreate, VariantResponse, StockUpdate, ProductUpdate, VariantUpdate
from app.services.producto_service import ProductService
from app.api.auth_deps import get_current_user
from typing import List, Optional

router = APIRouter()

@router.get("/", response_model=List[ProductResponse])
def get_products(categoria_id: Optional[int] = None, current_user = Depends(get_current_user)):
    return ProductService.get_products(categoria_id)

@router.get("/sku/{sku}", response_model=ProductResponse)
def get_product_by_sku(sku: str, current_user = Depends(get_current_user)):
    product = ProductService.get_product_by_sku(sku)
    if not product:
        raise HTTPException(status_code=404, detail="Product with this SKU not found")
    return product

@router.post("/", response_model=ProductResponse)
def create_product(product: ProductCreate, current_user = Depends(get_current_user)):
    return ProductService.create_product(product)

@router.patch("/{id}", response_model=ProductResponse)
def update_product(id: str, product_update: ProductUpdate, current_user = Depends(get_current_user)):
    product = ProductService.update_product(id, product_update)
    if not product:
         raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/variante", response_model=VariantResponse)
def create_variant(variant: VariantCreate, current_user = Depends(get_current_user)):
    return ProductService.create_variant(variant)

@router.patch("/variante/{id}", response_model=VariantResponse)
def update_variant(id: str, variant_update: VariantUpdate, current_user = Depends(get_current_user)):
    variant = ProductService.update_variant(id, variant_update)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
    return variant

@router.patch("/inventario/stock")
def update_stock(update: StockUpdate, current_user = Depends(get_current_user)):
    return ProductService.update_stock(update)
