from app.core.supabase import supabase
from app.schemas.caja import CajaApertura, CajaMovimiento, CajaCierre
from app.core.exceptions import CajaError
from uuid import UUID

class CajaService:
    @staticmethod
    def get_sesion_activa(usuario_id: str):
        res = supabase.table("sesiones_caja").select("*").eq("usuario_id", usuario_id).eq("estado", "abierta").execute()
        # Return first item if exists, else None
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    @staticmethod
    def abrir_caja(usuario_id: str, datos: CajaApertura):
        # We use the passed usuario_id which presumably comes from credentials or now from body?
        # The prompt said "solicitar tambien el uuid del usuario". 
        # So I should probably adhere to using the one passed in `datos` if the endpoint passes it.
        # But wait, looking at my plan: "Usage: CajaService.abrir_caja(datos.usuario_id, datos)".
        # So `usuario_id` arg will be `datos.usuario_id`.
        if CajaService.get_sesion_activa(usuario_id):
            raise CajaError("Ya existe una sesión de caja abierta.")
        
        nueva_sesion = {
            "usuario_id": usuario_id,
            "monto_apertura": datos.monto_apertura,
            "estado": "abierta"
        }
        res = supabase.table("sesiones_caja").insert(nueva_sesion).execute()
        return res.data[0]

    @staticmethod
    def registrar_movimiento(usuario_id: str, datos: CajaMovimiento):
        sesion = CajaService.get_sesion_activa(usuario_id)
        if not sesion:
            raise CajaError("No hay sesión de caja abierta.")
        
        movimiento = {
            "sesion_id": sesion["id"],
            "tipo": datos.tipo,
            "monto": datos.monto,
            "motivo": datos.motivo
        }
        res = supabase.table("movimientos_caja").insert(movimiento).select().execute()
        return res.data[0]

    @staticmethod
    def obtener_movimientos(usuario_id: str):
        sesion = CajaService.get_sesion_activa(usuario_id)
        if not sesion:
            raise CajaError("No hay sesión de caja abierta.")
        
        res = supabase.table("movimientos_caja").select("*").eq("sesion_id", sesion["id"]).execute()
        return res.data

    @staticmethod
    def cerrar_caja(usuario_id: str, datos: CajaCierre):
        sesion = CajaService.get_sesion_activa(usuario_id)
        if not sesion:
            raise CajaError("No hay sesión de caja abierta.")
        
        # Call RPC
        params = {
            "p_sesion_id": sesion["id"],
            "p_monto_real_efectivo": datos.monto_real_efectivo,
            "p_observaciones": datos.observaciones
        }
        res = supabase.rpc("finalizar_cierre_caja", params).execute()
        return res.data
