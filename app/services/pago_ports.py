"""Persistence port of the charge orchestration.

`PagoService` talks to the database only through `PagoStore`; the Supabase
adapter lives in `app/repositories/supabase_pago_store.py` and tests use an
in-memory implementation.
"""

from datetime import datetime
from typing import Any, Protocol

# States that hold the single "charge in flight" slot (partial unique index in the database).
ACTIVE_STATES = ("pendiente", "enviado", "indeterminado")


class ActiveChargeExists(Exception):
    """Another charge is pendiente / enviado / indeterminado: only one may be in flight."""


class SaleRejected(Exception):
    """The database refused to register the sale of a charge and rolled it back.

    `message` is the business reason when the database gave one that is safe to show
    (MU011 total changed, MU002 no stock, MU001 register closed, ...); None otherwise.
    Any other exception from `register_sale` means the outcome is unknown.
    """

    def __init__(self, message: str | None = None, code: str | None = None):
        super().__init__(message or code or "sale rejected")
        self.message = message
        self.code = code


class PagoStore(Protocol):
    def get_integration(self) -> dict | None:
        """The single `integracion_terminal` row, or None."""

    def update_integration(self, changes: dict, user_id: str) -> dict | None:
        """Apply a partial update stamped with time and user; the fresh row, or None."""

    def quote(self, carrito: dict, es_admin: bool) -> dict:
        """`cotizar_venta`: `{subtotal, descuento, recargo, total}` without writing. Raises the DB business errors."""

    def open_session_id(self) -> str | None:
        """Id of the open cash session, or None."""

    def register_sale(self, pago: dict) -> dict:
        """`registrar_venta_con_pago` for the charge's cart: the sale row. Idempotent per charge id.

        Raises `SaleRejected` when the database refused the sale (nothing was written).
        """

    def insert_pago(self, row: dict) -> dict:
        """Insert a charge. Raises `ActiveChargeExists` when another one is in flight."""

    def get_pago(self, pago_id: str) -> dict | None: ...

    def transition(self, pago_id: str, expected: str, new_estado: str, **fields: Any) -> dict | None:
        """Compare-and-set on `estado`: the updated row, or None when the charge was not in `expected`."""

    def set_attempts(self, pago_id: str, attempts: int) -> None:
        """Store `intentos_conciliacion` (not a transition: `updated_at` is left alone)."""

    def list_pagos(self, estado: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        """One page, newest first, plus the exact count of all matches."""

    def list_for_sweep(self, stale_before: datetime, max_attempts: int) -> list[dict]:
        """Charges to reconcile: every `indeterminado`, plus `pendiente` / `enviado` / `aprobado`
        not updated since `stale_before`; only those below `max_attempts`."""
