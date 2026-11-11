from datetime import datetime, timezone

from app.core.exceptions import StockError
from app.core.supabase import supabase
from app.schemas.productos import ProductCreate, ProductUpdate, StockUpdate, VariantCreate, VariantUpdate


class ProductService:
    @staticmethod
    def get_products(categoria_id: int | None = None):
        params = {}
        if categoria_id:
            params["p_categoria_id"] = categoria_id
            
        # Use RPC to filter by category if needed, and chain select to include variants
        query = supabase.rpc("obtener_productos", params).select("*, variantes:producto_variantes(*)")
            
        response = query.execute()
        return response.data

    @staticmethod
    def create_product(product: ProductCreate):
        response = supabase.table("productos").insert(product.model_dump(exclude_none=True)).execute()
        return response.data[0]

    @staticmethod
    def update_product(product_id: str, update_data: ProductUpdate):
        response = supabase.table("productos").update(update_data.model_dump(exclude_unset=True)).eq("id", product_id).execute()
        if not response.data:
            return None
        return response.data[0]

    @staticmethod
    def create_variant(variant: VariantCreate):
        response = supabase.table("producto_variantes").insert(variant.model_dump(exclude_none=True, mode='json')).execute()
        return response.data[0]

    @staticmethod
    def update_variant(variant_id: str, update_data: VariantUpdate):
        response = supabase.table("producto_variantes").update(update_data.model_dump(exclude_unset=True)).eq("id", variant_id).execute()
        if not response.data:
            return None
        return response.data[0]
    @staticmethod
    def update_stock(update: StockUpdate):
        variant_id = str(update.variante_id)
        
        # Get current stock
        res = supabase.table("producto_variantes").select("stock_actual, producto_id").eq("id", variant_id).single().execute()
        if not res.data:
            raise StockError("Variant not found")
        
        current_stock = res.data.get("stock_actual") or 0
        new_stock = current_stock + update.cantidad
        
        if new_stock < 0:
             raise StockError("Stock cannot be negative")

        # Update stock and variant updated_at
        now_iso = datetime.now(timezone.utc).isoformat()
        res_update = supabase.table("producto_variantes").update({
            "stock_actual": new_stock, 
            "updated_at": now_iso
        }).eq("id", variant_id).execute()
        
        # Also touch the product's updated_at
        producto_id = res.data.get("producto_id")
        if producto_id:
            supabase.table("productos").update({"updated_at": now_iso}).eq("id", producto_id).execute()
        
        return res_update.data[0]

    @staticmethod
    def get_product_by_sku(sku: str):
        # First find the variant to identify the product
        # explicit execute() without maybe_single() returns a list
        variant_res = supabase.table("producto_variantes").select("producto_id").eq("sku", sku).execute()
        
        # Check if we got a response and if data list is not empty
        if not variant_res or not variant_res.data:
            return None
            
        # Get the first match (sku should be unique)
        product_id = variant_res.data[0]["producto_id"]
        
        # Fetch the full product with all its variants
        product_res = supabase.table("productos").select("*, variantes:producto_variantes(*)").eq("id", product_id).single().execute()
        
        return product_res.data

    @staticmethod
    def delete_variant(variant_id: str) -> bool:
        """Elimina una variante si no tiene ventas asociadas."""
        # Verificar si la variante tiene ventas asociadas
        sales_check = supabase.table("venta_detalle").select("id").eq("variante_id", variant_id).limit(1).execute()
        if sales_check.data:
            raise ValueError("No se puede eliminar una variante que tiene ventas registradas")
        
        res = supabase.table("producto_variantes").delete().eq("id", variant_id).execute()
        return bool(res.data)

    @staticmethod
    def delete_product(product_id: str) -> bool:
        """Elimina un producto si no tiene variantes con ventas asociadas."""
        # Obtener variantes del producto
        variants_res = supabase.table("producto_variantes").select("id").eq("producto_id", product_id).execute()
        variant_ids = [v["id"] for v in (variants_res.data or [])]
        
        if variant_ids:
            # Verificar si alguna variante tiene ventas
            sales_check = supabase.table("venta_detalle").select("id").in_("variante_id", variant_ids).limit(1).execute()
            if sales_check.data:
                raise ValueError("No se puede eliminar un producto que tiene ventas registradas")
            # Eliminar variantes primero
            supabase.table("producto_variantes").delete().eq("producto_id", product_id).execute()
        
        # Eliminar categorias asociadas
        supabase.table("producto_categorias").delete().eq("producto_id", product_id).execute()

        res = supabase.table("productos").delete().eq("id", product_id).execute()
        return bool(res.data)
