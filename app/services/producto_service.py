from app.core.db_utils import fetch_all, single_row
from app.core.supabase import supabase
from app.schemas.productos import ProductCreate, ProductUpdate, StockUpdate, VariantCreate, VariantUpdate

STOCK_MOVEMENT_COLUMNS = (
    "id, created_at, tipo, cantidad, stock_resultante, venta_id, motivo, usuario:perfiles(id, nombre)"
)


class ProductService:
    @staticmethod
    def get_products(categoria_id: int | None = None):
        """Return the FULL catalog (the POS filters it client-side).

        The rows are fetched page by page so the result is never silently
        truncated at PostgREST's row cap.
        """
        params = {}
        if categoria_id:
            params["p_categoria_id"] = categoria_id

        # RPC filters by category when asked; the chained select embeds the variants.
        return fetch_all(
            lambda: supabase.rpc("obtener_productos", params)
            .select("*, variantes:producto_variantes(*)")
            .order("nombre")
            .order("id")
        )

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
    def update_stock(update: StockUpdate, usuario_id: str):
        """Apply a stock delta atomically through the `registrar_ajuste_stock` database function.

        The function also writes the movement (who, how much, why) to the stock ledger.
        Raises APIError MU004 (variant not found) or MU002 (stock would go negative).
        """
        params = {
            "p_variante_id": str(update.variante_id),
            "p_cantidad": update.cantidad,
            "p_usuario_id": str(usuario_id),
            "p_motivo": update.motivo,
        }
        res = supabase.rpc("registrar_ajuste_stock", params).execute()
        return single_row(res.data)

    @staticmethod
    def get_stock_movements(variant_id: str, limit: int = 50, offset: int = 0) -> dict:
        """One page of the stock ledger (kardex) of a variant, newest first, plus the exact count."""
        res = (
            supabase.table("movimientos_stock")
            .select(STOCK_MOVEMENT_COLUMNS, count="exact")
            .eq("variante_id", variant_id)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        items = res.data or []
        return {"items": items, "total": res.count if res.count is not None else len(items)}

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
