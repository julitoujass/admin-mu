from postgrest.exceptions import APIError

from app.core.db_utils import single_row
from app.core.exceptions import CajaError
from app.core.supabase import supabase
from app.schemas.caja import CajaApertura, CajaCierre, CajaMovimiento

NO_OPEN_SESSION = "No hay sesión de caja abierta."
ALREADY_OPEN = "Ya existe una sesión de caja abierta."
UNIQUE_VIOLATION = "23505"


class CajaService:
    @staticmethod
    def get_sesion_activa():
        """The single open cash session, or None.

        The register is global by business decision: there is one cash register
        shared by every user, and a unique index allows only one open session.
        """
        res = supabase.table("sesiones_caja").select("*").eq("estado", "abierta").limit(1).execute()
        return res.data[0] if res.data else None

    @staticmethod
    def _require_sesion_activa():
        sesion = CajaService.get_sesion_activa()
        if not sesion:
            raise CajaError(NO_OPEN_SESSION)
        return sesion

    @staticmethod
    def abrir_caja(usuario_id: str, datos: CajaApertura):
        """Open the register for `usuario_id` (always the authenticated user)."""
        if CajaService.get_sesion_activa():
            raise CajaError(ALREADY_OPEN, status_code=409)

        nueva_sesion = {
            "usuario_id": str(usuario_id),
            "monto_apertura": datos.monto_apertura,
            "estado": "abierta",
        }
        try:
            res = supabase.table("sesiones_caja").insert(nueva_sesion).execute()
        except APIError as exc:
            # Lost a race with another request: the unique index on open sessions rejected the insert.
            if exc.code == UNIQUE_VIOLATION:
                raise CajaError(ALREADY_OPEN, status_code=409) from exc
            raise
        return res.data[0]

    @staticmethod
    def registrar_movimiento(datos: CajaMovimiento):
        sesion = CajaService._require_sesion_activa()
        movimiento = {
            "sesion_id": sesion["id"],
            "tipo": datos.tipo,
            "monto": datos.monto,
            "motivo": datos.motivo,
        }
        res = supabase.table("movimientos_caja").insert(movimiento).execute()
        return res.data[0]

    @staticmethod
    def obtener_movimientos():
        sesion = CajaService._require_sesion_activa()
        res = supabase.table("movimientos_caja").select("*").eq("sesion_id", sesion["id"]).execute()
        return res.data

    @staticmethod
    def cerrar_caja(datos: CajaCierre):
        """Close the open session through the `cerrar_caja` database function.

        The function locks the session, computes the expected cash
        (opening + cash sales + ingresos - egresos) and returns the closed row.
        """
        sesion = CajaService._require_sesion_activa()
        params = {
            "p_sesion_id": sesion["id"],
            "p_monto_real_efectivo": datos.monto_real_efectivo,
            "p_observaciones": datos.observaciones,
        }
        res = supabase.rpc("cerrar_caja", params).execute()
        return single_row(res.data)

    @staticmethod
    def obtener_resumen():
        """Live totals of the open session (`resumen_caja`), or None when the register is closed."""
        sesion = CajaService.get_sesion_activa()
        if not sesion:
            return None
        res = supabase.rpc("resumen_caja", {"p_sesion_id": sesion["id"]}).execute()
        return single_row(res.data)

    @staticmethod
    def obtener_sesiones(limit: int = 200, offset: int = 0):
        res = (
            supabase.table("sesiones_caja")
            .select("*")
            .order("fecha_apertura", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return res.data

    @staticmethod
    def obtener_movimientos_por_sesion(sesion_id: str):
        # movimientos_caja uses 'creado_en' (not 'created_at') as its timestamp column.
        res = (
            supabase.table("movimientos_caja")
            .select("*")
            .eq("sesion_id", sesion_id)
            .order("creado_en", desc=True)
            .execute()
        )
        return res.data
