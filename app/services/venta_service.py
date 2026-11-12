from datetime import date, datetime, time

from app.core.db_utils import fetch_all, single_row
from app.core.supabase import supabase
from app.core.timeutils import ARGENTINA_TZ, local_day_bounds_utc, now_argentina
from app.schemas.ventas import VentaCreate

# Only what the POS needs; cost columns (total_costo) are never exposed here.
VENTA_PUBLIC_COLUMNS = "id, created_at, subtotal, descuento_aplicado, recargo_aplicado, total, metodo_pago, estado"

# `ventas` has two foreign keys to `perfiles` (usuario_id, anulada_por), so every
# embed of `perfiles` names the column it follows.
VENTA_LIST_COLUMNS = f"{VENTA_PUBLIC_COLUMNS}, cliente:clientes(id, nombre), usuario:perfiles!usuario_id(id, nombre)"


def _venta_detail_columns(include_costs: bool) -> str:
    """Select list of a sale with its items; cost columns are requested only when asked."""
    total_cost = ", total_costo" if include_costs else ""
    item_cost = ", costo_unitario" if include_costs else ""
    return (
        f"{VENTA_LIST_COLUMNS}, motivo_anulacion, anulada_at, anulada_por:perfiles!anulada_por(id, nombre){total_cost}, "
        f"items:venta_detalle(variante_id, cantidad, precio_unitario, subtotal{item_cost}, "
        "variante:producto_variantes(sku, talle, color, producto:productos(nombre)))"
    )


def _flatten_item(item: dict) -> dict:
    """Lift the embedded variant/product fields of a `venta_detalle` row to the top level."""
    variante = item.get("variante") or {}
    producto = variante.get("producto") or {}
    flat = {key: value for key, value in item.items() if key != "variante"}
    flat.update(
        sku=variante.get("sku"),
        talle=variante.get("talle"),
        color=variante.get("color"),
        producto_nombre=producto.get("nombre"),
    )
    return flat


def _local_date_bounds_utc(day: date) -> tuple[str, str]:
    """[start, end) of the Argentina local `day`, as UTC ISO strings."""
    return local_day_bounds_utc(datetime.combine(day, time.min, tzinfo=ARGENTINA_TZ))


def _now_local() -> datetime:
    return now_argentina()


class VentaService:
    @staticmethod
    def crear_venta(usuario_id: str, venta: VentaCreate, idempotency_key: str | None = None, es_admin: bool = False):
        """Create a sale atomically through the `registrar_venta` database function.

        The function locks the rows, reads prices and costs from the database,
        decrements stock, writes the detail and the stock ledger, and applies the
        discount/surcharge in one transaction. Only variant ids and quantities
        are sent: client-side prices and totals are not trusted. `es_admin` lifts
        the 10% discount limit that applies to employees (MU007).
        Business failures come back as APIError with an MU00x code (see main.py).
        """
        params = {
            "p_usuario_id": str(usuario_id),
            "p_metodo_pago": venta.metodo_pago,
            "p_items": [{"variante_id": str(item.variante_id), "cantidad": item.cantidad} for item in venta.items],
            "p_cliente_id": str(venta.cliente_id) if venta.cliente_id else None,
            "p_idempotency_key": idempotency_key,
            "p_descuento_tipo": venta.descuento.tipo if venta.descuento else None,
            "p_descuento_valor": venta.descuento.valor if venta.descuento else 0,
            "p_recargo_tipo": venta.recargo.tipo if venta.recargo else None,
            "p_recargo_valor": venta.recargo.valor if venta.recargo else 0,
            "p_es_admin": es_admin,
        }
        res = supabase.rpc("registrar_venta", params).execute()
        return single_row(res.data)

    @staticmethod
    def get_ventas_hoy():
        """Completed sales of the current Argentina local day, oldest first."""
        start, end = local_day_bounds_utc(_now_local())
        return fetch_all(
            lambda: supabase.table("ventas")
            .select(VENTA_PUBLIC_COLUMNS)
            .eq("estado", "completada")
            .gte("created_at", start)
            .lt("created_at", end)
            .order("created_at")
            .order("id")
        )

    @staticmethod
    def listar_ventas(
        desde: date | None = None,
        hasta: date | None = None,
        metodo_pago: str | None = None,
        estado: str | None = None,
        cliente_id: str | None = None,
        usuario_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """One page of sales, newest first, plus the exact count of all matches.

        `desde` / `hasta` are Argentina local dates, both inclusive.
        """
        query = supabase.table("ventas").select(VENTA_LIST_COLUMNS, count="exact")
        if desde:
            query = query.gte("created_at", _local_date_bounds_utc(desde)[0])
        if hasta:
            query = query.lt("created_at", _local_date_bounds_utc(hasta)[1])
        filters = {"metodo_pago": metodo_pago, "estado": estado, "cliente_id": cliente_id, "usuario_id": usuario_id}
        for column, value in filters.items():
            if value is not None:
                query = query.eq(column, value)
        res = (
            query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
        )
        items = res.data or []
        return {"items": items, "total": res.count if res.count is not None else len(items)}

    @staticmethod
    def get_venta(venta_id: str, include_costs: bool = False) -> dict | None:
        """A sale with its items, or None. Cost columns are only read when `include_costs`."""
        res = (
            supabase.table("ventas").select(_venta_detail_columns(include_costs)).eq("id", venta_id).limit(1).execute()
        )
        if not res.data:
            return None
        venta = res.data[0]
        return {**venta, "items": [_flatten_item(item) for item in venta.get("items") or []]}

    @staticmethod
    def anular_venta(venta_id: str, usuario_id: str, motivo: str):
        """Cancel a sale through the `anular_venta` database function.

        In one transaction it returns the stock (with its ledger rows), marks the
        sale as cancelled and, for a cash sale of an already closed session,
        records the refund as an egreso of the open register. Raises APIError
        MU004 (not found), MU006 (already cancelled), MU001 (cash refund needs an
        open register) or MU003 (empty reason).
        """
        params = {"p_venta_id": str(venta_id), "p_usuario_id": str(usuario_id), "p_motivo": motivo}
        res = supabase.rpc("anular_venta", params).execute()
        return single_row(res.data)
