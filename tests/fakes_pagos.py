"""In-memory stand-in for the `PagoStore` port, used by the payment service and endpoint tests."""

import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.pago_ports import ACTIVE_STATES, ActiveChargeExists

SESSION_ID = "55555555-5555-4555-8555-555555555555"
START = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


class InMemoryPagoStore:
    """Keeps charges in a dict and enforces the same rules as the database.

    - Only one charge may be in an active state (the partial unique index).
    - `transition` is a compare-and-set on `estado`.
    - `register_sale` is idempotent per charge id.
    """

    def __init__(self, habilitado=True, total=1500.0, session_id=SESSION_ID):
        self.integration = {
            "id": 1,
            "proveedor": "fake",
            "habilitado": habilitado,
            "device_id": None,
            "pos_id": None,
            "updated_at": None,
            "updated_by": None,
        }
        self.pagos: dict[str, dict] = {}
        self.sales: dict[str, dict] = {}
        self.quote_total = total
        self.quote_error: Exception | None = None
        self.quote_calls: list[tuple[dict, bool]] = []
        self.session_id = session_id
        # Exceptions raised by the next `register_sale` calls, in order.
        self.register_errors: list[Exception] = []
        self.register_calls: list[dict] = []
        self.now = START

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    # Integration settings -------------------------------------------------
    def get_integration(self):
        return copy.deepcopy(self.integration)

    def update_integration(self, changes, user_id):
        self.integration.update(changes, updated_at=self.now.isoformat(), updated_by=str(user_id))
        return self.get_integration()

    # Sales ------------------------------------------------------------------
    def quote(self, carrito, es_admin):
        self.quote_calls.append((carrito, es_admin))
        if self.quote_error:
            raise self.quote_error
        return {"subtotal": self.quote_total, "descuento": 0, "recargo": 0, "total": self.quote_total}

    def open_session_id(self):
        return self.session_id

    def register_sale(self, pago):
        self.register_calls.append(copy.deepcopy(pago))
        if self.register_errors:
            raise self.register_errors.pop(0)
        return self.sales.setdefault(
            pago["id"], {"id": str(uuid4()), "total": pago["monto"], "pago_externo_id": pago["id"]}
        )

    # Charges ----------------------------------------------------------------
    def insert_pago(self, row):
        if any(pago["estado"] in ACTIVE_STATES for pago in self.pagos.values()):
            raise ActiveChargeExists()
        pago = {
            "id": str(uuid4()),
            "venta_id": None,
            "proveedor_payment_id": None,
            "tarjeta_marca": None,
            "tarjeta_ultimos4": None,
            "codigo_autorizacion": None,
            "cuotas": None,
            "tipo_ingreso": None,
            "respuesta": None,
            "error": None,
            "intentos_conciliacion": 0,
            "created_at": self.now.isoformat(),
            "updated_at": self.now.isoformat(),
            **row,
        }
        self.pagos[pago["id"]] = pago
        return copy.deepcopy(pago)

    def get_pago(self, pago_id):
        pago = self.pagos.get(str(pago_id))
        return copy.deepcopy(pago) if pago else None

    def transition(self, pago_id, expected, new_estado, **fields):
        pago = self.pagos.get(str(pago_id))
        if not pago or pago["estado"] != expected:
            return None
        pago.update(fields, estado=new_estado, updated_at=self.now.isoformat())
        return copy.deepcopy(pago)

    def set_attempts(self, pago_id, attempts):
        self.pagos[str(pago_id)]["intentos_conciliacion"] = attempts

    def list_pagos(self, estado=None, limit=50, offset=0):
        rows = [pago for pago in self.pagos.values() if estado is None or pago["estado"] == estado]
        rows.sort(key=lambda pago: pago["created_at"], reverse=True)
        return copy.deepcopy(rows[offset : offset + limit]), len(rows)

    def list_for_sweep(self, stale_before, max_attempts):
        cutoff = stale_before.isoformat()
        return [
            copy.deepcopy(pago)
            for pago in self.pagos.values()
            if pago["intentos_conciliacion"] < max_attempts
            and (
                pago["estado"] == "indeterminado"
                or (pago["estado"] in ("pendiente", "enviado", "aprobado") and pago["updated_at"] < cutoff)
            )
        ]

    # Test helpers -------------------------------------------------------------
    def only(self):
        """The single charge of the test."""
        assert len(self.pagos) == 1
        return next(iter(self.pagos.values()))
