"""Orchestration of card / QR charges on a payment terminal.

Flow (see docs/design/plan-implementacion-clover.md, stage B):

    iniciar_cobro   quote -> insert `pendiente` -> schedule the background job
    ejecutar_cobro  pendiente -> enviado -> terminal.charge
                      APPROVED  -> aprobado -> registrar_venta_con_pago -> venta_registrada
                                   (rejected by the database -> error_registro -> full refund -> reembolsado)
                      DECLINED  -> rechazado          CANCELLED -> cancelado
                      UNKNOWN   -> indeterminado -> immediate reconciliation (lookups with backoff)
    conciliar_pendientes  safety net for charges whose process died or that stayed unknown

Rules that keep money and sales consistent:

- The terminal is charged at most once per `pago`: only the process that wins the
  `pendiente -> enviado` compare-and-set calls `charge`, and an unknown result is
  resolved with lookups, never with a second charge.
- Every state change is a compare-and-set (`PagoStore.transition`), so the background
  job, the sweep and an admin can touch the same charge without stepping on each other.
- A charge is refunded only when the database positively rejected the sale. If the
  outcome of the registration is unknown (connection lost) the charge stays `aprobado`
  and the sweep retries: the registration is idempotent per charge id.

This module depends on two ports only: `PaymentTerminal` and `PagoStore`.
"""

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Sequence
from uuid import uuid4

from app.core.exceptions import PagoError
from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeRequest,
    ChargeResult,
    PaymentTerminal,
    RefundOutcome,
    TerminalBadRequest,
    TerminalBusy,
)
from app.services.pago_ports import ActiveChargeExists, PagoStore, SaleRejected

logger = logging.getLogger(__name__)

ENTITY = "pagos_externos"

INTEGRATION_DISABLED = "La integración con el terminal está deshabilitada"
CHARGE_IN_PROGRESS = "Ya hay un cobro en curso"
PAGO_NOT_FOUND = "Pago no encontrado"
NO_OPEN_SESSION = "No hay sesión de caja abierta."
INVALID_TOTAL = "El total a cobrar debe ser mayor a 0"
TERMINAL_BUSY = "Terminal ocupado"
TERMINAL_REJECTED_REQUEST = "El terminal rechazó la solicitud de cobro"
TERMINAL_HAS_NO_CHARGE = "El terminal no registra el cobro"
SALE_NOT_REGISTERED = "No se pudo registrar la venta"
REFUND_NOT_CONFIRMED = "reembolso no confirmado: revisar en el terminal"
CANCEL_FAILED = "No se pudo cancelar el cobro en el terminal"

# Keys of a provider response that may carry card data; dropped before storing it.
_SENSITIVE_KEY = re.compile(
    r"pan|cardnumber|number|track|cvv|cvc|cvn|expir|token|holder|first6|pin|emv|vaulted", re.IGNORECASE
)
_CARD_NUMBER = re.compile(r"\d{12,19}")

AuditFn = Callable[..., None]
ScheduleFn = Callable[..., Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_provider_response(value: Any) -> Any:
    """Copy of a provider response without anything that looks like card data."""
    if isinstance(value, dict):
        return {
            key: sanitize_provider_response(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_provider_response(item) for item in value]
    if isinstance(value, str):
        return _CARD_NUMBER.sub("[redacted]", value)
    return value


def to_cents(amount: Any) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PagoService:
    def __init__(
        self,
        terminal: PaymentTerminal,
        store: PagoStore,
        provider: str,
        audit: AuditFn,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utcnow,
        backoff: Sequence[float] = (2, 5, 10),
        stale_seconds: float = 180,
        max_attempts: int = 10,
        ping_timeout: float = 2.0,
    ):
        self._terminal = terminal
        self._store = store
        self._provider = provider
        self._audit_fn = audit
        self._sleep = sleep
        self._now = now
        self._backoff = tuple(backoff)
        self._stale_seconds = stale_seconds
        self._max_attempts = max_attempts
        self._ping_timeout = ping_timeout

    # --- Starting a charge (inside the request) ---------------------------------

    def iniciar_cobro(self, cobro, user, schedule: ScheduleFn) -> dict:
        """Quote the cart, reserve the terminal with a `pendiente` charge and schedule the job.

        `schedule(func, *args)` must run `func` outside the request (FastAPI's
        `BackgroundTasks.add_task`): the charge blocks until the customer pays.
        """
        integration = self._store.get_integration()
        if not integration or not integration.get("habilitado"):
            raise PagoError(INTEGRATION_DISABLED, status_code=409)

        es_admin = getattr(user, "rol", None) == "admin"
        carrito = {
            "items": [{"variante_id": str(item.variante_id), "cantidad": item.cantidad} for item in cobro.items],
            "cliente_id": str(cobro.cliente_id) if cobro.cliente_id else None,
            "descuento": cobro.descuento.model_dump() if cobro.descuento else None,
            "recargo": cobro.recargo.model_dump() if cobro.recargo else None,
            # The discount limit is decided with the role the user had when the charge started.
            "es_admin": es_admin,
        }
        # The store raises the same business errors as a sale (MU001 / MU002 / MU003 / MU004 / MU007).
        total = float(self._store.quote(carrito, es_admin)["total"])
        if total <= 0:
            raise PagoError(INVALID_TOTAL, status_code=400)
        sesion_id = self._store.open_session_id()
        if not sesion_id:
            raise PagoError(NO_OPEN_SESSION, status_code=400)

        try:
            pago = self._store.insert_pago(
                {
                    "proveedor": self._provider,
                    "external_payment_id": uuid4().hex,  # 32 characters
                    "estado": "pendiente",
                    "metodo_pago": cobro.metodo_pago,
                    "monto": total,
                    "carrito": carrito,
                    "sesion_caja": str(sesion_id),
                    "usuario_id": str(user.id),
                }
            )
        except ActiveChargeExists:
            raise PagoError(CHARGE_IN_PROGRESS, status_code=409) from None

        self._audit(pago, "CHARGE_STARTED")
        schedule(self.ejecutar_cobro, pago["id"])
        return {"pago_id": pago["id"], "total": total, "estado": pago["estado"]}

    # --- The background job --------------------------------------------------------

    def ejecutar_cobro(self, pago_id: str) -> None:
        """Charge on the terminal and act on the result. Safe to run more than once."""
        pago = self._store.transition(pago_id, "pendiente", "enviado")
        if pago is None:
            # Already taken by another run, cancelled, or resolved by the sweep: never charge twice.
            return
        try:
            result = self._charge(pago)
            if result is None:
                return
            pago = self._apply_result(pago, "enviado", result)
            if pago is not None and pago["estado"] == "indeterminado":
                self._reconcile_now(pago)
        finally:
            self._show_welcome()

    def _charge(self, pago: dict) -> ChargeResult | None:
        """Result of the charge, or None when the terminal refused to start it (nothing was charged)."""
        request = ChargeRequest(
            external_id=pago["external_payment_id"],
            amount_cents=to_cents(pago["monto"]),
            metodo=pago["metodo_pago"],
            description="Venta POS",
        )
        try:
            return self._terminal.charge(request)
        except TerminalBusy:
            self._reject(pago, "enviado", TERMINAL_BUSY)
        except TerminalBadRequest:
            logger.error("The terminal rejected the charge request of pago %s as invalid", pago["id"])
            self._reject(pago, "enviado", TERMINAL_REJECTED_REQUEST)
        except Exception as exc:
            # Unreachable terminal, timeout or adapter bug: the customer may have been charged.
            logger.warning("Charge of pago %s ended without a result (%s)", pago["id"], type(exc).__name__)
            return ChargeResult(outcome=ChargeOutcome.UNKNOWN)
        return None

    def _apply_result(self, pago: dict, expected: str, result: ChargeResult) -> dict | None:
        """Move the charge from `expected` to the state its terminal result means.

        Returns the updated charge, or None when another process changed it first.
        """
        if result.outcome is ChargeOutcome.APPROVED:
            approved = self._store.transition(
                pago["id"],
                expected,
                "aprobado",
                proveedor_payment_id=result.provider_payment_id,
                tarjeta_marca=result.card_brand,
                tarjeta_ultimos4=result.last4,
                codigo_autorizacion=result.auth_code,
                cuotas=result.installments,
                tipo_ingreso=result.entry_type,
                respuesta=sanitize_provider_response(result.raw),
            )
            if approved is None:
                return None
            self._audit(approved, "CHARGE_APPROVED")
            return self._register_sale(approved)
        if result.outcome is ChargeOutcome.DECLINED:
            return self._reject(pago, expected, result.error or "Pago rechazado")
        if result.outcome is ChargeOutcome.CANCELLED:
            cancelled = self._store.transition(pago["id"], expected, "cancelado")
            if cancelled is not None:
                self._audit(cancelled, "CHARGE_CANCELLED")
            return cancelled
        if expected == "indeterminado":
            return pago
        unknown = self._store.transition(pago["id"], expected, "indeterminado")
        if unknown is not None:
            self._audit(unknown, "CHARGE_UNKNOWN")
        return unknown

    def _reject(self, pago: dict, expected: str, error: str) -> dict | None:
        rejected = self._store.transition(pago["id"], expected, "rechazado", error=error)
        if rejected is not None:
            self._audit(rejected, "CHARGE_FAILED")
        return rejected

    def _reconcile_now(self, pago: dict) -> None:
        """Immediate reconciliation: the cashier and the customer are waiting at the counter."""
        for wait in self._backoff:
            self._sleep(wait)
            found, _ = self._lookup(pago)
            if found is not None and found.outcome is not ChargeOutcome.UNKNOWN:
                self._apply_result(pago, "indeterminado", found)
                return
        logger.warning("Pago %s is still indeterminate after the immediate lookups; left for the sweep", pago["id"])

    def _lookup(self, pago: dict) -> tuple[ChargeResult | None, bool]:
        """`(result, answered)`: `answered` is False when the terminal could not be asked."""
        try:
            return self._terminal.find_by_external_id(pago["external_payment_id"]), True
        except Exception as exc:
            logger.warning("Lookup of pago %s failed (%s)", pago["id"], type(exc).__name__)
            return None, False

    # --- Registering the sale and refunding ----------------------------------------------

    def _register_sale(self, pago: dict) -> dict | None:
        """Register the sale of an `aprobado` charge; refund it if the database rejects the sale."""
        try:
            venta = self._register_with_retry(pago)
        except SaleRejected as exc:
            # The database answered: the sale was rolled back (MU011, MU002, MU001, ...).
            logger.error("Sale of pago %s rejected by the database: code=%s", pago["id"], exc.code)
            failed = self._store.transition(
                pago["id"], "aprobado", "error_registro", error=exc.message or SALE_NOT_REGISTERED
            )
            if failed is None:
                return None
            self._audit(failed, "CHARGE_FAILED")
            return self._refund(failed)
        except Exception:
            # Unknown outcome: the sale may exist. Refunding could leave a sale without payment,
            # so the charge stays `aprobado` and the sweep retries the idempotent registration.
            logger.exception("Could not register the sale of pago %s; it stays aprobado for the sweep", pago["id"])
            return pago

        registered = self._store.transition(pago["id"], "aprobado", "venta_registrada", venta_id=venta["id"])
        if registered is not None:
            self._emit(
                pago.get("usuario_id"),
                "CREATE_SALE",
                entidad="ventas",
                entidad_id=venta["id"],
                descripcion=f"Total: ${venta.get('total')} (cobro en terminal)",
                payload={"pago_externo_id": pago["id"], "metodo_pago": pago["metodo_pago"]},
            )
        return registered

    def _register_with_retry(self, pago: dict) -> dict:
        try:
            return self._store.register_sale(pago)
        except SaleRejected:
            raise
        except Exception:
            logger.warning("Registration of pago %s lost its connection; retrying once", pago["id"])
            return self._store.register_sale(pago)

    def _refund(self, pago: dict) -> dict | None:
        """Full refund of a charge whose sale could not be registered. Never retried blindly."""
        payment_id = pago.get("proveedor_payment_id")
        outcome = RefundOutcome.UNKNOWN
        if payment_id:
            try:
                outcome = self._terminal.refund(payment_id, None).outcome
            except Exception as exc:
                logger.error("Refund of pago %s failed (%s)", pago["id"], type(exc).__name__)
        if outcome is RefundOutcome.DONE:
            refunded = self._store.transition(pago["id"], "error_registro", "reembolsado")
            if refunded is not None:
                self._audit(refunded, "REFUND_DONE")
            return refunded
        logger.error("Pago %s was charged, has no sale and its refund is not confirmed: needs admin review", pago["id"])
        return self._store.transition(
            pago["id"], "error_registro", "error_registro", error=f"{pago.get('error')}; {REFUND_NOT_CONFIRMED}"
        )

    # --- Reconciliation ---------------------------------------------------------------------

    def conciliar_pendientes(self) -> None:
        """Sweep of orphan charges: unresolved `indeterminado` ones and those left behind by a dead process."""
        stale_before = self._now() - timedelta(seconds=self._stale_seconds)
        for pago in self._store.list_for_sweep(stale_before, self._max_attempts):
            try:
                self._reconcile(pago)
            except Exception:
                logger.exception("Reconciliation of pago %s failed", pago.get("id"))

    def conciliar_pago(self, pago_id: str) -> dict:
        """Reconcile one charge now (admin), whatever its number of attempts."""
        pago = self._store.get_pago(pago_id)
        if pago is None:
            raise PagoError(PAGO_NOT_FOUND, status_code=404)
        self._reconcile(pago)
        return self._store.get_pago(pago_id)

    def _reconcile(self, pago: dict) -> None:
        estado = pago["estado"]
        if estado == "aprobado":
            # Charged but the process died (or lost the database) before registering the sale.
            self._count_attempt(pago)
            self._register_sale(pago)
            return
        if estado not in ("pendiente", "enviado", "indeterminado"):
            return
        attempts = self._count_attempt(pago)
        found, answered = self._lookup(pago)
        if found is not None and found.outcome is not ChargeOutcome.UNKNOWN:
            self._apply_result(pago, estado, found)
        elif answered and found is None and self._is_stale(pago):
            # The charge window is over and the terminal has no such payment: nothing was charged.
            self._reject(pago, estado, TERMINAL_HAS_NO_CHARGE)
        elif attempts >= self._max_attempts:
            logger.warning(
                "Pago %s is still %s after %s reconciliation attempts: left for admin review", pago["id"], estado, attempts
            )

    def _count_attempt(self, pago: dict) -> int:
        attempts = int(pago.get("intentos_conciliacion") or 0) + 1
        self._store.set_attempts(pago["id"], attempts)
        return attempts

    def _is_stale(self, pago: dict) -> bool:
        """Whether the last state change is older than the charge window."""
        try:
            updated_at = datetime.fromisoformat(str(pago["updated_at"]))
        except (KeyError, ValueError):
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return updated_at < self._now() - timedelta(seconds=self._stale_seconds)

    # --- Reading, cancelling, reviewing --------------------------------------------------------

    def get_pago(self, pago_id: str, user) -> dict:
        """The charge, for the user who started it or an admin; anyone else gets 404."""
        pago = self._store.get_pago(pago_id)
        is_admin = getattr(user, "rol", None) == "admin"
        if pago is None or not (is_admin or str(pago.get("usuario_id")) == str(user.id)):
            raise PagoError(PAGO_NOT_FOUND, status_code=404)
        return pago

    def cancelar(self, pago_id: str, user) -> dict:
        """Cancel a charge that is still in flight. The final state is decided by the charge itself."""
        pago = self.get_pago(pago_id, user)
        if pago["estado"] == "pendiente":
            cancelled = self._store.transition(pago_id, "pendiente", "cancelado")
            if cancelled is not None:  # not sent yet: nothing to cancel on the device
                self._audit(cancelled, "CHARGE_CANCELLED")
                return cancelled
            pago = self._store.get_pago(pago_id) or pago
        if pago["estado"] == "enviado":
            try:
                self._terminal.cancel_current()
            except Exception as exc:
                logger.warning("Cancel of pago %s failed (%s)", pago_id, type(exc).__name__)
                raise PagoError(CANCEL_FAILED, status_code=503) from None
        return pago

    def listar(self, estado: str | None, limit: int, offset: int) -> dict:
        items, total = self._store.list_pagos(estado, limit, offset)
        return {"items": items, "total": total}

    # --- Integration settings ------------------------------------------------------------------

    def estado_integracion(self) -> dict:
        integration = self._store.get_integration() or {}
        return {
            "proveedor": self._provider,
            "habilitado": bool(integration.get("habilitado")),
            "conectado": self._ping(),
            "device_id": integration.get("device_id"),
            "pos_id": integration.get("pos_id"),
            "updated_at": integration.get("updated_at"),
        }

    def actualizar_integracion(self, changes: dict, user) -> dict:
        # The adapter in use comes from the environment; the row only mirrors it.
        row = self._store.update_integration({**changes, "proveedor": self._provider}, str(user.id))
        if row is None:
            raise PagoError("Integración no configurada", status_code=404)
        self._emit(str(user.id), "TERMINAL_SETTINGS", entidad="integracion_terminal", entidad_id=1, payload=changes)
        return self.estado_integracion()

    def _ping(self) -> bool:
        """Ping with a deadline, so a hanging device never hangs the POS."""
        answer: list[bool] = []

        def ask() -> None:
            try:
                answer.append(bool(self._terminal.ping()))
            except Exception:
                answer.append(False)

        worker = threading.Thread(target=ask, name="terminal-ping", daemon=True)
        worker.start()
        worker.join(self._ping_timeout)
        return bool(answer and answer[0])

    # --- Helpers ----------------------------------------------------------------------------------

    def _show_welcome(self) -> None:
        try:
            self._terminal.show_welcome()
        except Exception as exc:
            logger.warning("Could not reset the terminal screen (%s)", type(exc).__name__)

    def _audit(self, pago: dict, evento: str) -> None:
        """Audit a charge event. Only brand and last 4 digits of the card are recorded."""
        payload = {
            "estado": pago.get("estado"),
            "metodo_pago": pago.get("metodo_pago"),
            "monto": pago.get("monto"),
            "proveedor": pago.get("proveedor"),
            "external_payment_id": pago.get("external_payment_id"),
            "tarjeta_marca": pago.get("tarjeta_marca"),
            "tarjeta_ultimos4": pago.get("tarjeta_ultimos4"),
            "venta_id": pago.get("venta_id"),
            "error": pago.get("error"),
        }
        self._emit(pago.get("usuario_id"), evento, entidad=ENTITY, entidad_id=pago["id"], payload=payload)

    def _emit(self, usuario_id: Any, evento: str, **fields: Any) -> None:
        """Audit is best effort: it must never break a charge that already moved money."""
        try:
            self._audit_fn(usuario_id, evento, **fields)
        except Exception:
            logger.exception("Could not write the %s audit record", evento)
