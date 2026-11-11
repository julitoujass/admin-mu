from app.core.supabase import supabase
from app.schemas.catalogos import CategoriaCreate, CategoriaUpdate, MarcaCreate, MarcaUpdate


class CatalogoService:
    # ============ MARCAS ============
    @staticmethod
    def get_marcas():
        res = supabase.table("marcas").select("*").order("nombre").execute()
        return res.data

    @staticmethod
    def create_marca(marca: MarcaCreate):
        res = supabase.table("marcas").insert(marca.model_dump(exclude_none=True)).execute()
        return res.data[0]

    @staticmethod
    def update_marca(marca_id: int, update_data: MarcaUpdate):
        res = supabase.table("marcas").update(update_data.model_dump(exclude_unset=True)).eq("id", marca_id).execute()
        if not res.data:
            return None
        return res.data[0]

    @staticmethod
    def delete_marca(marca_id: int) -> bool:
        # Integridad referencial manual (ya que RLS está deshabilitado y no hay foreign key cascade a la vista)
        check_prod = supabase.table("productos").select("id").eq("marca_id", marca_id).limit(1).execute()
        if check_prod.data:
            raise ValueError("No se puede eliminar la marca porque hay productos asignados a ella.")

        res = supabase.table("marcas").delete().eq("id", marca_id).execute()
        return bool(res.data)

    # ============ CATEGORIAS ============
    @staticmethod
    def get_categorias():
        res = supabase.table("categorias").select("*").order("nombre").execute()
        return res.data

    @staticmethod
    def create_categoria(categoria: CategoriaCreate):
        res = supabase.table("categorias").insert(categoria.model_dump(exclude_none=True)).execute()
        return res.data[0]

    @staticmethod
    def update_categoria(categoria_id: int, update_data: CategoriaUpdate):
        res = supabase.table("categorias").update(update_data.model_dump(exclude_unset=True)).eq("id", categoria_id).execute()
        if not res.data:
            return None
        return res.data[0]

    @staticmethod
    def delete_categoria(categoria_id: int) -> bool:
        # Integridad referencial
        check_prod = supabase.table("producto_categorias").select("producto_id").eq("categoria_id", categoria_id).limit(1).execute()
        if check_prod.data:
            raise ValueError("No se puede eliminar la categoría porque hay productos asignados a ella.")

        res = supabase.table("categorias").delete().eq("id", categoria_id).execute()
        return bool(res.data)
