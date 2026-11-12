from datetime import datetime, timezone

from app.core.supabase import supabase

SETTINGS_ID = 1
SETTINGS_COLUMNS = "*, updated_by:perfiles!updated_by(id, nombre)"


class ConfiguracionService:
    @staticmethod
    def get() -> dict | None:
        """The single settings row (id = 1) with the editor embedded as `{id, nombre}`, or None."""
        res = supabase.table("configuracion").select(SETTINGS_COLUMNS).eq("id", SETTINGS_ID).limit(1).execute()
        return res.data[0] if res.data else None

    @staticmethod
    def update(changes: dict, user_id: str) -> dict | None:
        """Apply a partial update stamped with the time and the user; returns the fresh row or None."""
        values = {**changes, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": str(user_id)}
        res = supabase.table("configuracion").update(values).eq("id", SETTINGS_ID).execute()
        if not res.data:
            return None
        return ConfiguracionService.get()
