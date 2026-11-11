from datetime import datetime

from app.core.db_utils import fetch_all, single_row
from app.core.supabase import supabase
from app.core.timeutils import local_day_bounds_utc, now_argentina
from app.schemas.ventas import VentaCreate

# Only what the POS needs; cost columns (total_costo) are never exposed.
VENTA_PUBLIC_COLUMNS = "id, created_at, total, metodo_pago"


def _now_local() -> datetime:
    return now_argentina()


class VentaService:
    @staticmethod
    def crear_venta(usuario_id: str, venta: VentaCreate, idempotency_key: str | None = None):
        """Create a sale atomically through the `crear_venta` database function.

        The function locks the rows, reads prices and costs from the database,
        decrements stock and writes the detail in one transaction. Only variant
        ids and quantities are sent: client-side prices and totals are not trusted.
        Business failures come back as APIError with an MU00x code (see main.py).
        """
        params = {
            "p_usuario_id": str(usuario_id),
            "p_metodo_pago": venta.metodo_pago,
            "p_items": [{"variante_id": str(item.variante_id), "cantidad": item.cantidad} for item in venta.items],
            "p_cliente_id": str(venta.cliente_id) if venta.cliente_id else None,
            "p_idempotency_key": idempotency_key,
        }
        res = supabase.rpc("crear_venta", params).execute()
        return single_row(res.data)

    @staticmethod
    def get_ventas_hoy():
        """Sales of the current Argentina local day, oldest first."""
        start, end = local_day_bounds_utc(_now_local())
        return fetch_all(
            lambda: supabase.table("ventas")
            .select(VENTA_PUBLIC_COLUMNS)
            .gte("created_at", start)
            .lt("created_at", end)
            .order("created_at")
            .order("id")
        )
