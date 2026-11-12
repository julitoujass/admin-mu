from datetime import date, datetime, time

from app.core.supabase import supabase
from app.core.timeutils import ARGENTINA_TZ, local_day_bounds_utc

LOG_COLUMNS = "id, created_at, evento, entidad, entidad_id, descripcion, estado, payload_enviado, respuesta_recibida, usuario_id"


def _day_bounds(day: date) -> tuple[str, str]:
    return local_day_bounds_utc(datetime.combine(day, time.min, tzinfo=ARGENTINA_TZ))


class AuditoriaService:
    @staticmethod
    def listar(
        desde: date | None = None,
        hasta: date | None = None,
        evento: str | None = None,
        entidad: str | None = None,
        usuario_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """One page of the audit log, newest first, plus the exact count of all matches.

        `desde` / `hasta` are Argentina local dates, both inclusive. The author's name is read
        from `perfiles` in a second query (no dependency on a foreign key of `logs`).
        """
        query = supabase.table("logs").select(LOG_COLUMNS, count="exact")
        if desde:
            query = query.gte("created_at", _day_bounds(desde)[0])
        if hasta:
            query = query.lt("created_at", _day_bounds(hasta)[1])
        filters = {"evento": evento, "entidad": entidad, "usuario_id": usuario_id}
        for column, value in filters.items():
            if value is not None:
                query = query.eq(column, value)
        res = query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
        rows = res.data or []

        user_ids = sorted({str(row["usuario_id"]) for row in rows if row.get("usuario_id")})
        names: dict[str, dict] = {}
        if user_ids:
            profiles = supabase.table("perfiles").select("id, nombre").in_("id", user_ids).execute().data or []
            names = {str(profile["id"]): profile for profile in profiles}

        items = []
        for row in rows:
            rest = {key: value for key, value in row.items() if key != "usuario_id"}
            profile = names.get(str(row.get("usuario_id")))
            items.append({**rest, "usuario": {"id": profile["id"], "nombre": profile.get("nombre")} if profile else None})
        return {"items": items, "total": res.count if res.count is not None else len(items)}
