"""Supabase adapter of the `PagoStore` port (tables `pagos_externos` and `integracion_terminal`)."""

from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from app.core.db_utils import single_row
from app.core.supabase import supabase
from app.services.pago_ports import ActiveChargeExists, SaleRejected

PAGOS = "pagos_externos"
INTEGRATION = "integracion_terminal"
INTEGRATION_ID = 1
UNIQUE_VIOLATION = "23505"
# The review list never needs the cart snapshot nor the raw provider response.
PAGO_LIST_COLUMNS = (
    "id, proveedor, external_payment_id, estado, metodo_pago, monto, venta_id, usuario_id, tarjeta_marca, "
    "tarjeta_ultimos4, codigo_autorizacion, cuotas, error, intentos_conciliacion, created_at, updated_at"
)
STALE_CANDIDATE_STATES = ["pendiente", "enviado", "aprobado"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabasePagoStore:
    # Integration settings ---------------------------------------------------------
    def get_integration(self) -> dict | None:
        res = supabase.table(INTEGRATION).select("*").eq("id", INTEGRATION_ID).limit(1).execute()
        return res.data[0] if res.data else None

    def update_integration(self, changes: dict, user_id: str) -> dict | None:
        values = {**changes, "updated_at": _now_iso(), "updated_by": str(user_id)}
        res = supabase.table(INTEGRATION).update(values).eq("id", INTEGRATION_ID).execute()
        return res.data[0] if res.data else None

    # Sales ------------------------------------------------------------------------
    def quote(self, carrito: dict, es_admin: bool) -> dict:
        res = supabase.rpc("cotizar_venta", {"p_items": carrito["items"], **_adjustment_params(carrito, es_admin)}).execute()
        return single_row(res.data)

    def open_session_id(self) -> str | None:
        res = supabase.table("sesiones_caja").select("id").eq("estado", "abierta").limit(1).execute()
        return res.data[0]["id"] if res.data else None

    def register_sale(self, pago: dict) -> dict:
        carrito = pago["carrito"]
        params = {
            "p_pago_externo_id": str(pago["id"]),
            "p_usuario_id": str(pago["usuario_id"]),
            "p_metodo_pago": pago["metodo_pago"],
            "p_items": carrito["items"],
            "p_total_esperado": pago["monto"],
            "p_cliente_id": carrito.get("cliente_id"),
            **_adjustment_params(carrito, bool(carrito.get("es_admin"))),
        }
        try:
            res = supabase.rpc("registrar_venta_con_pago", params).execute()
        except APIError as exc:
            # The database answered with an error, so the whole sale was rolled back.
            # Only the messages of our own MU codes are written by us and safe to show.
            is_business = bool(exc.code) and str(exc.code).startswith("MU") and bool(exc.message)
            raise SaleRejected(exc.message if is_business else None, exc.code) from exc
        return single_row(res.data)

    # Charges ----------------------------------------------------------------------
    def insert_pago(self, row: dict) -> dict:
        try:
            res = supabase.table(PAGOS).insert(row).execute()
        except APIError as exc:
            # Besides the single-active-charge index, the only unique column is the external id.
            if exc.code == UNIQUE_VIOLATION and "external_payment_id" not in f"{exc.message} {exc.details}":
                raise ActiveChargeExists() from exc
            raise
        return res.data[0]

    def get_pago(self, pago_id: str) -> dict | None:
        res = supabase.table(PAGOS).select("*").eq("id", str(pago_id)).limit(1).execute()
        return res.data[0] if res.data else None

    def transition(self, pago_id: str, expected: str, new_estado: str, **fields: Any) -> dict | None:
        values = {**fields, "estado": new_estado, "updated_at": _now_iso()}
        res = supabase.table(PAGOS).update(values).eq("id", str(pago_id)).eq("estado", expected).execute()
        return res.data[0] if res.data else None

    def set_attempts(self, pago_id: str, attempts: int) -> None:
        supabase.table(PAGOS).update({"intentos_conciliacion": attempts}).eq("id", str(pago_id)).execute()

    def list_pagos(self, estado: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        query = supabase.table(PAGOS).select(PAGO_LIST_COLUMNS, count="exact")
        if estado is not None:
            query = query.eq("estado", estado)
        res = query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
        items = res.data or []
        return items, res.count if res.count is not None else len(items)

    def list_for_sweep(self, stale_before: datetime, max_attempts: int) -> list[dict]:
        unknown = (
            supabase.table(PAGOS)
            .select("*")
            .eq("estado", "indeterminado")
            .lt("intentos_conciliacion", max_attempts)
            .order("created_at")
            .execute()
        )
        stale = (
            supabase.table(PAGOS)
            .select("*")
            .in_("estado", STALE_CANDIDATE_STATES)
            .lt("updated_at", stale_before.isoformat())
            .lt("intentos_conciliacion", max_attempts)
            .order("created_at")
            .execute()
        )
        return [*(unknown.data or []), *(stale.data or [])]


def _adjustment_params(carrito: dict, es_admin: bool) -> dict:
    descuento = carrito.get("descuento") or {}
    recargo = carrito.get("recargo") or {}
    return {
        "p_descuento_tipo": descuento.get("tipo"),
        "p_descuento_valor": descuento.get("valor", 0),
        "p_recargo_tipo": recargo.get("tipo"),
        "p_recargo_valor": recargo.get("valor", 0),
        "p_es_admin": es_admin,
    }
