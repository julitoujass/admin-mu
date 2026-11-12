from datetime import date
from typing import Any, Dict, List, Optional

from app.core.supabase import supabase

# All aggregation happens in SQL (functions reporte_ventas, reporte_productos_top,
# reporte_cajas). They bucket by Argentina local date and treat a null bound as open.


def _range_params(fecha_inicio: Optional[date], fecha_fin: Optional[date]) -> Dict[str, Optional[str]]:
    return {
        "p_desde": fecha_inicio.isoformat() if fecha_inicio else None,
        "p_hasta": fecha_fin.isoformat() if fecha_fin else None,
    }


class ReporteService:
    @staticmethod
    def obtener_ventas_por_rango(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> Dict[str, Any]:
        data = supabase.rpc("reporte_ventas", _range_params(fecha_inicio, fecha_fin)).execute().data or {}
        return {
            "total_ingresos": data.get("total_ingresos") or 0,
            "total_bruto": data.get("total_bruto") or 0,
            "total_devoluciones": data.get("total_devoluciones") or 0,
            "cantidad_operaciones": data.get("cantidad_operaciones") or 0,
            "ventas_por_dia": data.get("ventas_por_dia") or [],
        }

    @staticmethod
    def obtener_top_productos(
        fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None, limite: int = 50
    ) -> List[Dict[str, Any]]:
        params = {**_range_params(fecha_inicio, fecha_fin), "p_limite": limite}
        return supabase.rpc("reporte_productos_top", params).execute().data or []

    @staticmethod
    def obtener_resumen_cajas(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> Dict[str, Any]:
        data = supabase.rpc("reporte_cajas", _range_params(fecha_inicio, fecha_fin)).execute().data or {}
        return {
            "resumen_diario": data.get("resumen_diario") or [],
            "diferencia_total_periodo": data.get("diferencia_total_periodo") or 0,
        }
