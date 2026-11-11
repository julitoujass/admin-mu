from app.core.exceptions import UsuarioError
from app.core.supabase import supabase

ADMIN_ROLE = "admin"
PROFILE_COLUMNS = "*, roles(id, nombre)"

USER_NOT_FOUND = "Usuario no encontrado"
ROLE_NOT_FOUND = "El rol indicado no existe"
SELF_DEMOTION = "No podés quitarte el rol de administrador"
SELF_DEACTIVATION = "No podés desactivar tu propio usuario"
LAST_ADMIN = "Debe quedar al menos un administrador activo"


def _is_admin(usuario: dict) -> bool:
    return (usuario.get("roles") or {}).get("nombre") == ADMIN_ROLE


class UsuarioService:
    @staticmethod
    def get_usuarios():
        res = supabase.table("perfiles").select(PROFILE_COLUMNS).order("created_at", desc=True).execute()
        return res.data

    @staticmethod
    def get_roles():
        res = supabase.table("roles").select("id, nombre").execute()
        return res.data

    @staticmethod
    def get_usuario(usuario_id: str):
        """Profile with its embedded role, or None."""
        res = supabase.table("perfiles").select(PROFILE_COLUMNS).eq("id", usuario_id).limit(1).execute()
        return res.data[0] if res.data else None

    @staticmethod
    def _require_usuario(usuario_id: str) -> dict:
        usuario = UsuarioService.get_usuario(usuario_id)
        if not usuario:
            raise UsuarioError(USER_NOT_FOUND, status_code=404)
        return usuario

    @staticmethod
    def _require_another_active_admin(usuario: dict) -> None:
        """Refuse a change that would take the last active admin away.

        Only matters when `usuario` is an active admin today. This is a check
        followed by a write (not atomic): two simultaneous requests could both
        pass it.
        """
        if not (_is_admin(usuario) and usuario.get("activo")):
            return
        res = (
            supabase.table("perfiles")
            .select("id")
            .eq("rol_id", usuario["roles"]["id"])
            .eq("activo", True)
            .neq("id", usuario["id"])
            .limit(1)
            .execute()
        )
        if not res.data:
            raise UsuarioError(LAST_ADMIN, status_code=409)

    @staticmethod
    def update_rol(usuario_id: str, rol_id: int, actor_id: str):
        """Change a user's role. `actor_id` is the admin making the change."""
        usuario = UsuarioService._require_usuario(usuario_id)

        role_res = supabase.table("roles").select("id, nombre").eq("id", rol_id).limit(1).execute()
        if not role_res.data:
            raise UsuarioError(ROLE_NOT_FOUND, status_code=400)
        new_role = role_res.data[0]

        if _is_admin(usuario) and new_role["nombre"] != ADMIN_ROLE:
            if str(usuario_id) == str(actor_id):
                raise UsuarioError(SELF_DEMOTION, status_code=409)
            UsuarioService._require_another_active_admin(usuario)

        res = supabase.table("perfiles").update({"rol_id": rol_id}).eq("id", usuario_id).execute()
        if not res.data:
            raise UsuarioError(USER_NOT_FOUND, status_code=404)
        return {**res.data[0], "roles": new_role}

    @staticmethod
    def set_activo(usuario_id: str, activo: bool, actor_id: str):
        """Activate or deactivate a user. `actor_id` is the admin making the change."""
        usuario = UsuarioService._require_usuario(usuario_id)

        if not activo:
            if str(usuario_id) == str(actor_id):
                raise UsuarioError(SELF_DEACTIVATION, status_code=409)
            UsuarioService._require_another_active_admin(usuario)

        res = supabase.table("perfiles").update({"activo": activo}).eq("id", usuario_id).execute()
        if not res.data:
            raise UsuarioError(USER_NOT_FOUND, status_code=404)
        return {**res.data[0], "roles": usuario.get("roles")}
