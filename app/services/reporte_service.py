from app.core.supabase import supabase
from datetime import date
from typing import Optional, Dict, Any, List
from collections import defaultdict

class ReporteService:
    @staticmethod
    def obtener_ventas_por_rango(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> Dict[str, Any]:
        query = supabase.table("ventas").select("id, total, created_at")
        
        if fecha_inicio:
            query = query.gte("created_at", f"{fecha_inicio}T00:00:00")
        if fecha_fin:
            query = query.lte("created_at", f"{fecha_fin}T23:59:59")
            
        res = query.execute()
        ventas = res.data
        
        total_ingresos = 0.0
        cantidad_operaciones = len(ventas)
        ventas_por_dia_map = defaultdict(lambda: {"total": 0.0, "cantidad": 0})
        
        for venta in ventas:
            total_ingresos += venta["total"]
            # Extract date (YYYY-MM-DD) from ISO format created_at 
            dia = venta["created_at"].split("T")[0]
            ventas_por_dia_map[dia]["total"] += venta["total"]
            ventas_por_dia_map[dia]["cantidad"] += 1
            
        ventas_por_dia_list = [
            {
                "fecha": dia,
                "total": data["total"],
                "cantidad_ventas": data["cantidad"]
            }
            for dia, data in sorted(ventas_por_dia_map.items())
        ]
        
        return {
            "total_ingresos": total_ingresos,
            "cantidad_operaciones": cantidad_operaciones,
            "ventas_por_dia": ventas_por_dia_list
        }

    @staticmethod
    def obtener_top_productos(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> List[Dict[str, Any]]:
        # As supabase-py doesn't have complex joins easily accessible via REST without views or RPCs,
        # We fetch all the data needed and aggregate in memory. In a large production DB, we'd use an RPC.
        # This is fine for the scale expected.
        
        # Primero obtenemos las ventas en el rango
        ventas_query = supabase.table("ventas").select("id, created_at")
        if fecha_inicio:
            ventas_query = ventas_query.gte("created_at", f"{fecha_inicio}T00:00:00")
        if fecha_fin:
            ventas_query = ventas_query.lte("created_at", f"{fecha_fin}T23:59:59")
        
        ventas_res = ventas_query.execute()
        ventas_ids = [v["id"] for v in ventas_res.data]
        
        if not ventas_ids:
            return []
            
        # Obtenemos los items de esas ventas
        items_res = supabase.table("venta_detalle").select("variante_id, cantidad, precio_unitario, venta_id").in_("venta_id", ventas_ids).execute()
        
        # Agregamos por variante
        top_map = defaultdict(lambda: {"cantidad": 0, "ingresos": 0.0})
        variantes_ids = set()
        
        for item in items_res.data:
            var_id = item["variante_id"]
            top_map[var_id]["cantidad"] += item["cantidad"]
            top_map[var_id]["ingresos"] += (item["cantidad"] * item["precio_unitario"])
            variantes_ids.add(var_id)
            
        if not variantes_ids:
            return []
            
        # Obtener los detalles de los productos/variantes para el reporte
        # (producto_variantes tiene fk al producto)
        variantes_res = supabase.table("producto_variantes").select("id, talle, color, producto_id").in_("id", list(variantes_ids)).execute()
        
        productos_ids = {v["producto_id"] for v in variantes_res.data}
        productos_res = supabase.table("productos").select("id, nombre").in_("id", list(productos_ids)).execute()
        
        productos_dict = {p["id"]: p["nombre"] for p in productos_res.data}
        variantes_dict = {
            v["id"]: {
                "talle": v["talle"], 
                "color": v["color"], 
                "nombre_producto": productos_dict.get(v["producto_id"], "Desconocido")
            } 
            for v in variantes_res.data
        }
        
        resultado = []
        for var_id, stats in top_map.items():
            var_info = variantes_dict.get(var_id, {})
            resultado.append({
                "variante_id": var_id,
                "nombre_producto": var_info.get("nombre_producto", "Desconocido"),
                "talle": var_info.get("talle"),
                "color": var_info.get("color"),
                "cantidad_vendida": stats["cantidad"],
                "ingresos_generados": stats["ingresos"]
            })
            
        # Ordenar por ingresos generados
        resultado.sort(key=lambda x: x["ingresos_generados"], reverse=True)
        return resultado

    @staticmethod
    def obtener_resumen_cajas(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> Dict[str, Any]:
        query = supabase.table("sesiones_caja").select("*")
        
        if fecha_inicio:
            query = query.gte("fecha_apertura", f"{fecha_inicio}T00:00:00")
        if fecha_fin:
            # We want sessions closed within that day, or at least opened on that day. Let's filter by fecha_apertura.
            query = query.lte("fecha_apertura", f"{fecha_fin}T23:59:59")
            
        res = query.execute()
        sesiones = res.data
        
        if not sesiones:
            return {
                "resumen_diario": [],
                "diferencia_total_periodo": 0.0
            }
            
        # Obtener movimientos para estas sesiones en una sola query (si es que no son demasiados, pero para el reporte es util)
        sesion_ids = [s["id"] for s in sesiones]
        mov_res = supabase.table("movimientos_caja").select("sesion_id, tipo, monto").in_("sesion_id", sesion_ids).execute()
        
        # Agrupar movimientos por sesion
        movimientos_por_sesion = defaultdict(lambda: {"ingreso": 0.0, "egreso": 0.0})
        for mov in mov_res.data:
            s_id = mov["sesion_id"]
            tipo = mov["tipo"]
            movimientos_por_sesion[s_id][tipo] += float(mov["monto"] or 0)
            
        # Agrupar resumenes por dia
        resumen_diario_map = defaultdict(lambda: {
            "sesiones_abiertas": 0,
            "monto_inicial_total": 0.0,
            "ingresos": 0.0,
            "egresos": 0.0,
            "monto_real_efectivo_total": 0.0,
            "diferencia_esperado_vs_real": 0.0
        })
        
        for sesion in sesiones:
            # Dia de la apertura
            dia = sesion["fecha_apertura"].split("T")[0]
            s_id = sesion["id"]
            
            inicial = float(sesion["monto_apertura"] or 0)
            real = float(sesion["monto_real_efectivo"] or 0) if sesion["monto_real_efectivo"] is not None else 0.0
            esperado = float(sesion["monto_esperado_efectivo"] or 0) if sesion["monto_esperado_efectivo"] is not None else 0.0
            
            # If expected is null (e.g., opened but not closed), we might estimate it based on movements.
            if sesion["estado"] == "abierta":
                esperado = inicial + movimientos_por_sesion[s_id]["ingreso"] - movimientos_por_sesion[s_id]["egreso"]
                real = 0 # Not closed yet
                diferencia = 0
            else:
                diferencia = real - esperado
            
            resumen_diario_map[dia]["sesiones_abiertas"] += 1
            resumen_diario_map[dia]["monto_inicial_total"] += inicial
            resumen_diario_map[dia]["ingresos"] += movimientos_por_sesion[s_id]["ingreso"]
            resumen_diario_map[dia]["egresos"] += movimientos_por_sesion[s_id]["egreso"]
            resumen_diario_map[dia]["monto_real_efectivo_total"] += real
            resumen_diario_map[dia]["diferencia_esperado_vs_real"] += diferencia
            
        resumen_diario_list = []
        diferencia_total = 0.0
        
        for dia, data in sorted(resumen_diario_map.items()):
            resumen_diario_list.append({
                "fecha": dia,
                "sesiones_abiertas": data["sesiones_abiertas"],
                "monto_inicial_total": data["monto_inicial_total"],
                "ingresos": data["ingresos"],
                "egresos": data["egresos"],
                "monto_real_efectivo_total": data["monto_real_efectivo_total"],
                "diferencia_esperado_vs_real": data["diferencia_esperado_vs_real"]
            })
            diferencia_total += data["diferencia_esperado_vs_real"]
            
        return {
            "resumen_diario": resumen_diario_list,
            "diferencia_total_periodo": diferencia_total
        }
