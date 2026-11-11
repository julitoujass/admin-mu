import logging

from app.core.supabase import supabase


class LogService:
    @staticmethod
    def registrar_log(
        usuario_id: str,
        evento: str,
        entidad: str = None,
        entidad_id: str = None,
        descripcion: str = None,
        payload_enviado: dict = None,
        respuesta_recibida: dict = None,
        estado: str = "SUCCESS"
    ):
        """
        Registra una acción en la base de datos (tabla logs).
        Diseñado para ser ejecutado como BackgroundTask de FastAPI.
        """
        log_data = {
            "evento": evento,
            "estado": estado
        }
        
        if usuario_id:
            log_data["usuario_id"] = str(usuario_id)
        if entidad:
            log_data["entidad"] = entidad
        if entidad_id:
            log_data["entidad_id"] = str(entidad_id)
        if descripcion:
            log_data["descripcion"] = descripcion
        if payload_enviado is not None:
            log_data["payload_enviado"] = payload_enviado
        if respuesta_recibida is not None:
            log_data["respuesta_recibida"] = respuesta_recibida

        try:
            supabase.table("logs").insert(log_data).execute()
        except Exception as e:
            # Fallback in case of DB issue so it does not silent-fail completely without trace
            logging.error(f"Error guardando auditoria en DB: {e}")
