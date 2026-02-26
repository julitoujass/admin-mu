from app.core.supabase import supabase
from app.schemas.productos import ProductCreate, VariantCreate, StockUpdate, ProductUpdate, VariantUpdate
from app.core.exceptions import StockError

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
        res = supabase.table("producto_variantes").select("stock_actual").eq("id", variant_id).single().execute()
        if not res.data:
            raise StockError("Variant not found")
        
        current_stock = res.data["stock_actual"]
        new_stock = current_stock + update.cantidad
        
        if new_stock < 0:
             raise StockError("Stock cannot be negative")

        # Update stock
        res_update = supabase.table("producto_variantes").update({"stock_actual": new_stock}).eq("id", variant_id).execute()
        
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
