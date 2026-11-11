
from app.core.exceptions import CajaError
from app.core.supabase import supabase
from app.schemas.caja import CajaApertura, CajaCierre, CajaMovimiento


class CajaService:
    @staticmethod
    def get_sesion_activa(usuario_id: str = None):
        # Global register (ignoring usuario_id parameter constraint)
        res = supabase.table("sesiones_caja").select("*").eq("estado", "abierta").execute()
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
        res = supabase.table("movimientos_caja").insert(movimiento).execute()
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
        
        # Unwrap list if RPC returns an array
        if isinstance(res.data, list) and len(res.data) > 0:
            return res.data[0]
        elif isinstance(res.data, list):
            return {**sesion, "estado": "cerrada"}
        return res.data

    @staticmethod
    def obtener_sesiones():
        res = supabase.table("sesiones_caja").select("*").order("fecha_apertura", desc=True).execute()
        return res.data

    @staticmethod
    def obtener_movimientos_por_sesion(sesion_id: str):
        # Asumiendo que la columna de fecha de creación en db es 'creado_en' basado en el schema
        res = supabase.table("movimientos_caja").select("*").eq("sesion_id", sesion_id).order("creado_en", desc=True).execute()
        return res.data
