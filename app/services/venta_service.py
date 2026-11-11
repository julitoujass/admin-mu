
from app.core.exceptions import CajaError, StockError
from app.core.supabase import supabase
from app.schemas.ventas import VentaCreate
from app.services.caja_service import CajaService


class VentaService:
    @staticmethod
    def crear_venta(usuario_id: str, venta: VentaCreate):
        # 1. Check open session
        sesion = CajaService.get_sesion_activa(usuario_id)
        if not sesion:
            raise CajaError("No hay sesión de caja abierta.")

        # 2. Validate Stock & Calculate Total
        total = 0
        items_data = []
        
        for item in venta.items:
            # Check stock
            res = supabase.table("producto_variantes").select("stock_actual, precio_costo").eq("id", str(item.variante_id)).single().execute()
            if not res.data:
                raise StockError(f"Variante {item.variante_id} no encontrada")
            
            variant = res.data
            if variant["stock_actual"] < item.cantidad:
                raise StockError(f"Stock insuficiente para variante {item.variante_id}")
            
            subtotal = item.cantidad * item.precio_unitario
            total += subtotal
            
            items_data.append({
                "variante_id": str(item.variante_id),
                "cantidad": item.cantidad,
                "precio_unitario": item.precio_unitario,
                "costo_unitario": variant.get("precio_costo", 0)
            })

        # 3. Calcular total_costo
        total_costo = sum(
            (item_d["costo_unitario"] or 0) * item_d["cantidad"]
            for item_d in items_data
        )

        # 4. Insert Venta
        venta_data = {
            "usuario_id": usuario_id,
            "sesion_caja": sesion["id"],
            "total": total,
            "total_costo": total_costo,
            "metodo_pago": venta.metodo_pago,
            "cliente_id": str(venta.cliente_id) if venta.cliente_id else None
        }
        res_venta = supabase.table("ventas").insert(venta_data).execute()
        venta_id = res_venta.data[0]["id"]

        # 5. Insert Items & Update Stock
        for item_data in items_data:
            item_data["venta_id"] = venta_id
            supabase.table("venta_detalle").insert(item_data).execute()
            
            # Update stock
            current_variant = supabase.table("producto_variantes").select("stock_actual").eq("id", item_data["variante_id"]).single().execute()
            new_stock = current_variant.data["stock_actual"] - item_data["cantidad"]
            supabase.table("producto_variantes").update({"stock_actual": new_stock}).eq("id", item_data["variante_id"]).execute()

        return res_venta.data[0]

    @staticmethod
    def get_ventas_hoy():
        from datetime import datetime
        today = datetime.now().date().isoformat()
        # Filter by created_at >= today (start of day)
        res = supabase.table("ventas").select("*").gte("created_at", today).execute()
        return res.data
