from app.core.supabase import supabase
from app.schemas.usuarios import UsuarioRoleUpdate


class UsuarioService:
    @staticmethod
    def get_usuarios():
        res = supabase.table("perfiles").select("*, roles(id, nombre)").order("created_at", desc=True).execute()
        return res.data

    @staticmethod
    def get_roles():
        res = supabase.table("roles").select("id, nombre").execute()
        return res.data

    @staticmethod
    def update_rol(id: str, update: UsuarioRoleUpdate):
        res = supabase.table("perfiles").update({"rol_id": update.rol_id}).eq("id", id).execute()
        return res.data[0] if res.data else None
